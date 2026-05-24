"""Tests for POST /api/webhooks/twilio/voice/ (v5 voice scaffold).

The view answers the call with bilingual TwiML and records a phone-channel
Conversation row. No STT, no TTS, no agent loop. See
``docs/voice-implementation-plan.md`` for what comes next.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from twilio.request_validator import RequestValidator

from core.models import Conversation, Customer, Store

WEBHOOK_URL = reverse("api:twilio-voice-webhook")


def _sign(url: str, params: dict, token: str) -> str:
    return RequestValidator(token).compute_signature(url, params)


@pytest.fixture()
def absolute_url() -> str:
    # Django test client posts against http://testserver/...; the absolute
    # URL is what Twilio's validator HMACs against.
    return f"http://testserver{WEBHOOK_URL}"


@pytest.mark.django_db(transaction=True)
def test_returns_503_when_token_unset(client, settings):
    settings.TWILIO_AUTH_TOKEN = ""
    resp = client.post(WEBHOOK_URL, {"From": "+14165550111", "CallSid": "CA1"})
    assert resp.status_code == 503
    assert resp.json() == {"error": "not_configured"}
    assert Conversation.objects.filter(channel="phone").count() == 0


@pytest.mark.django_db(transaction=True)
def test_returns_403_on_tampered_signature(client, settings):
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    resp = client.post(
        WEBHOOK_URL,
        {"From": "+14165550111", "CallSid": "CA1"},
        HTTP_X_TWILIO_SIGNATURE="obviously-wrong",
    )
    assert resp.status_code == 403
    assert resp.json() == {"error": "invalid_signature"}
    # Nothing written when signature is rejected.
    assert Conversation.objects.filter(channel="phone").count() == 0


@pytest.mark.django_db(transaction=True)
def test_valid_signed_call_returns_bilingual_twiml(client, settings, absolute_url):
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "+14165550111", "CallSid": "CA-abc"}
    sig = _sign(absolute_url, params, settings.TWILIO_AUTH_TOKEN)
    resp = client.post(WEBHOOK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)

    assert resp.status_code == 200
    assert "application/xml" in resp["Content-Type"]
    body = resp.content.decode()
    # Both <Say> elements present with correct language attributes.
    assert '<Say voice="Polly.Joanna" language="en-US">' in body
    assert '<Say voice="Polly.Zhiyu" language="cmn-CN">' in body
    # English copy mentions "PlayDesk" and "text" so the caller knows the
    # fallback channel; Mandarin copy mentions 中文 (the literal "Chinese").
    assert "PlayDesk" in body
    assert "text" in body
    # The Mandarin char 中 (中) appears either literally or as an
    # entity — both are valid TwiML.
    assert "中" in body or "&#20013;" in body


@pytest.mark.django_db(transaction=True)
def test_unknown_caller_creates_anonymous_phone_conversation(client, settings, absolute_url):
    """An inbound call from a phone we've never seen records an anonymous row."""
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    # Hand-craft a number with formatting noise to prove the normaliser runs.
    params = {"From": "+1 (416) 555-0188", "CallSid": "CA-anon"}
    sig = _sign(absolute_url, params, settings.TWILIO_AUTH_TOKEN)
    resp = client.post(WEBHOOK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)

    assert resp.status_code == 200
    convs = Conversation.objects.filter(channel="phone")
    assert convs.count() == 1
    # Stored as E.164.
    assert convs.first().customer_identifier == "+14165550188"


@pytest.mark.django_db(transaction=True)
def test_known_caller_links_via_customer_identifier(client, settings, absolute_url):
    """A caller whose normalised phone matches an existing Customer.

    The Conversation has no FK to Customer in v5, so linkage is via
    ``customer_identifier`` (same E.164 string the Customer is keyed on).
    This test pins the contract so a future migration that adds the FK
    can land without breaking the lookup pattern.
    """
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    store = Store.objects.create(name="Test Store")
    Customer.objects.create(store=store, phone="+14165550111", name="Alice")

    params = {"From": "+14165550111", "CallSid": "CA-known"}
    sig = _sign(absolute_url, params, settings.TWILIO_AUTH_TOKEN)
    resp = client.post(WEBHOOK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)

    assert resp.status_code == 200
    conv = Conversation.objects.get(channel="phone")
    assert conv.customer_identifier == "+14165550111"
