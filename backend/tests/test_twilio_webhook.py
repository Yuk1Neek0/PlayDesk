"""Tests for POST /api/webhooks/twilio/sms/."""

from __future__ import annotations

from unittest import mock

import pytest
from django.urls import reverse

WEBHOOK_URL = reverse("api:twilio-sms-webhook")


def _sign(url: str, params: dict, token: str) -> str:
    """Compute a valid Twilio signature so we don't have to hand-craft one."""
    from twilio.request_validator import RequestValidator

    return RequestValidator(token).compute_signature(url, params)


@pytest.fixture(autouse=True)
def _allow_post_url() -> str:
    # Django test client's POST builds the absolute URL via the test
    # server's host. We just need that URL for signature computation.
    return f"http://testserver{WEBHOOK_URL}"


@pytest.mark.django_db(transaction=True)
def test_returns_503_when_token_unset(client, settings):
    settings.TWILIO_AUTH_TOKEN = ""
    resp = client.post(WEBHOOK_URL, {"From": "+14165550111", "Body": "hi"})
    assert resp.status_code == 503
    assert resp.json() == {"error": "not_configured"}


@pytest.mark.django_db(transaction=True)
def test_returns_403_on_tampered_signature(client, settings, _allow_post_url):
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    resp = client.post(
        WEBHOOK_URL,
        {"From": "+14165550111", "Body": "hi"},
        HTTP_X_TWILIO_SIGNATURE="obviously-wrong-signature",
    )
    assert resp.status_code == 403
    assert resp.json() == {"error": "invalid_signature"}


@pytest.mark.django_db(transaction=True)
def test_returns_403_when_signature_header_missing(client, settings):
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    resp = client.post(WEBHOOK_URL, {"From": "+14165550111", "Body": "hi"})
    assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_valid_signature_runs_agent_and_returns_twiml(client, settings, _allow_post_url):
    """Happy path: valid signature → 200 TwiML carrying the assistant reply.

    The AgentLoop is patched so we don't need an LLM key.
    """
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "+1 (416) 555-0111", "Body": "Is the PS5 free Saturday 8 pm?"}
    sig = _sign(_allow_post_url, params, settings.TWILIO_AUTH_TOKEN)

    with mock.patch("api.webhooks_twilio.AgentLoop") as MockLoop:
        instance = MockLoop.return_value
        instance.run.return_value = {
            "message_id": 1,
            "text": "Sure! PS5 Station 1 is free 8–10 pm Saturday.",
            "booking_id": None,
            "iteration_count": 2,
        }
        resp = client.post(
            WEBHOOK_URL,
            params,
            HTTP_X_TWILIO_SIGNATURE=sig,
        )

    assert resp.status_code == 200
    assert "application/xml" in resp["Content-Type"]
    body = resp.content.decode()
    assert "<Response>" in body
    assert "<Message>" in body
    assert "PS5 Station 1 is free" in body


@pytest.mark.django_db(transaction=True)
def test_creates_conversation_with_channel_sms(client, settings, _allow_post_url):
    """The webhook find-or-creates a Conversation tagged channel='sms'."""
    from core.models import Conversation

    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "+14165550111", "Body": "hello"}
    sig = _sign(_allow_post_url, params, settings.TWILIO_AUTH_TOKEN)

    with mock.patch("api.webhooks_twilio.AgentLoop") as MockLoop:
        MockLoop.return_value.run.return_value = {
            "text": "hi back",
            "booking_id": None,
            "iteration_count": 1,
        }
        client.post(WEBHOOK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)

    convs = Conversation.objects.filter(channel="sms", customer_identifier="+14165550111")
    assert convs.count() == 1


@pytest.mark.django_db(transaction=True)
def test_repeat_sms_from_same_phone_reuses_conversation(client, settings, _allow_post_url):
    """Two inbound SMS from the same number share a single Conversation."""
    from core.models import Conversation

    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "+14165550111", "Body": "msg one"}
    sig = _sign(_allow_post_url, params, settings.TWILIO_AUTH_TOKEN)

    with mock.patch("api.webhooks_twilio.AgentLoop") as MockLoop:
        MockLoop.return_value.run.return_value = {
            "text": "ack",
            "booking_id": None,
            "iteration_count": 1,
        }
        client.post(WEBHOOK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)
        params2 = {"From": "+14165550111", "Body": "msg two"}
        sig2 = _sign(_allow_post_url, params2, settings.TWILIO_AUTH_TOKEN)
        client.post(WEBHOOK_URL, params2, HTTP_X_TWILIO_SIGNATURE=sig2)

    assert Conversation.objects.filter(channel="sms").count() == 1


@pytest.mark.django_db(transaction=True)
def test_empty_body_returns_empty_twiml_no_agent_call(client, settings, _allow_post_url):
    """An empty SMS body short-circuits — no agent loop runs."""
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "+14165550111", "Body": ""}
    sig = _sign(_allow_post_url, params, settings.TWILIO_AUTH_TOKEN)

    with mock.patch("api.webhooks_twilio.AgentLoop") as MockLoop:
        resp = client.post(WEBHOOK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)
        MockLoop.assert_not_called()

    assert resp.status_code == 200
    assert "<Response>" in resp.content.decode()
