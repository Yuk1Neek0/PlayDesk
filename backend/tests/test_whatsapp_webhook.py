"""Tests for POST /api/webhooks/twilio/whatsapp/."""

from __future__ import annotations

from unittest import mock

import pytest
from django.urls import reverse

WEBHOOK_URL = reverse("api:twilio-whatsapp-webhook")


def _sign(url: str, params: dict, token: str) -> str:
    """Compute a valid Twilio signature so we don't hand-craft one."""
    from twilio.request_validator import RequestValidator

    return RequestValidator(token).compute_signature(url, params)


@pytest.fixture(autouse=True)
def _allow_post_url() -> str:
    # Django test client POSTs to /testserver; we need the absolute URL
    # for signature computation.
    return f"http://testserver{WEBHOOK_URL}"


@pytest.mark.django_db(transaction=True)
def test_returns_503_when_token_unset(client, settings):
    settings.TWILIO_AUTH_TOKEN = ""
    resp = client.post(
        WEBHOOK_URL,
        {"From": "whatsapp:+14165550111", "Body": "hi"},
    )
    assert resp.status_code == 503
    assert resp.json() == {"error": "not_configured"}


@pytest.mark.django_db(transaction=True)
def test_returns_403_on_tampered_signature(client, settings, _allow_post_url):
    from core.models import Conversation

    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    resp = client.post(
        WEBHOOK_URL,
        {"From": "whatsapp:+14165550111", "Body": "hi"},
        HTTP_X_TWILIO_SIGNATURE="obviously-wrong-signature",
    )
    assert resp.status_code == 403
    assert resp.json() == {"error": "invalid_signature"}
    # Tampered request must not create a Conversation row.
    assert Conversation.objects.filter(channel="whatsapp").count() == 0


@pytest.mark.django_db(transaction=True)
def test_returns_403_when_signature_header_missing(client, settings):
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    resp = client.post(WEBHOOK_URL, {"From": "whatsapp:+14165550111", "Body": "hi"})
    assert resp.status_code == 403


@pytest.mark.django_db(transaction=True)
def test_valid_signature_runs_agent_and_returns_twiml(client, settings, _allow_post_url):
    """Happy path: valid signature → 200 TwiML carrying the assistant reply."""
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "whatsapp:+14165550111", "Body": "今晚有 PS5 吗？"}
    sig = _sign(_allow_post_url, params, settings.TWILIO_AUTH_TOKEN)

    with mock.patch("api.webhooks_twilio.AgentLoop") as MockLoop:
        instance = MockLoop.return_value
        instance.run.return_value = {
            "message_id": 1,
            "text": "Yes! PS5 Station 1 is free 8–10 pm tonight.",
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
def test_creates_conversation_with_channel_whatsapp(client, settings, _allow_post_url):
    """The webhook find-or-creates a Conversation tagged channel='whatsapp'.

    The `customer_identifier` is the normalised E.164 (no `whatsapp:` prefix).
    """
    from core.models import Conversation

    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "whatsapp:+14165550111", "Body": "hello"}
    sig = _sign(_allow_post_url, params, settings.TWILIO_AUTH_TOKEN)

    with mock.patch("api.webhooks_twilio.AgentLoop") as MockLoop:
        MockLoop.return_value.run.return_value = {
            "text": "hi back",
            "booking_id": None,
            "iteration_count": 1,
        }
        client.post(WEBHOOK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)

    convs = Conversation.objects.filter(channel="whatsapp", customer_identifier="+14165550111")
    assert convs.count() == 1


@pytest.mark.django_db(transaction=True)
def test_repeat_whatsapp_from_same_phone_reuses_conversation(client, settings, _allow_post_url):
    """Two inbound WhatsApp from the same number share a single Conversation."""
    from core.models import Conversation

    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "whatsapp:+14165550111", "Body": "msg one"}
    sig = _sign(_allow_post_url, params, settings.TWILIO_AUTH_TOKEN)

    with mock.patch("api.webhooks_twilio.AgentLoop") as MockLoop:
        MockLoop.return_value.run.return_value = {
            "text": "ack",
            "booking_id": None,
            "iteration_count": 1,
        }
        client.post(WEBHOOK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)
        params2 = {"From": "whatsapp:+14165550111", "Body": "msg two"}
        sig2 = _sign(_allow_post_url, params2, settings.TWILIO_AUTH_TOKEN)
        client.post(WEBHOOK_URL, params2, HTTP_X_TWILIO_SIGNATURE=sig2)

    assert Conversation.objects.filter(channel="whatsapp").count() == 1


@pytest.mark.django_db(transaction=True)
def test_empty_body_returns_empty_twiml_no_agent_call(client, settings, _allow_post_url):
    """An empty WhatsApp body short-circuits — no agent loop runs."""
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "whatsapp:+14165550111", "Body": ""}
    sig = _sign(_allow_post_url, params, settings.TWILIO_AUTH_TOKEN)

    with mock.patch("api.webhooks_twilio.AgentLoop") as MockLoop:
        resp = client.post(WEBHOOK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)
        MockLoop.assert_not_called()

    assert resp.status_code == 200
    assert "<Response>" in resp.content.decode()


@pytest.mark.django_db(transaction=True)
def test_sms_and_whatsapp_from_same_phone_are_separate_conversations(
    client, settings, _allow_post_url
):
    """Same E.164 over SMS and over WhatsApp → two distinct Conversations."""
    from core.models import Conversation

    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    # WhatsApp message first.
    wa_params = {"From": "whatsapp:+14165550111", "Body": "via wa"}
    wa_sig = _sign(_allow_post_url, wa_params, settings.TWILIO_AUTH_TOKEN)
    sms_url = reverse("api:twilio-sms-webhook")
    sms_params = {"From": "+14165550111", "Body": "via sms"}
    sms_sig = _sign(f"http://testserver{sms_url}", sms_params, settings.TWILIO_AUTH_TOKEN)

    with mock.patch("api.webhooks_twilio.AgentLoop") as MockLoop:
        MockLoop.return_value.run.return_value = {
            "text": "ok",
            "booking_id": None,
            "iteration_count": 1,
        }
        client.post(WEBHOOK_URL, wa_params, HTTP_X_TWILIO_SIGNATURE=wa_sig)
        client.post(sms_url, sms_params, HTTP_X_TWILIO_SIGNATURE=sms_sig)

    assert (
        Conversation.objects.filter(customer_identifier="+14165550111", channel="whatsapp").count()
        == 1
    )
    assert (
        Conversation.objects.filter(customer_identifier="+14165550111", channel="sms").count() == 1
    )
