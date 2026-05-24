"""Tests for POST /api/webhooks/twilio/voice/status/ (missed-call rows).

The view captures Twilio's call-status callbacks. Missed/failed/cancelled
calls write a phone Conversation row with ``status='abandoned``; the
``completed`` status is skipped because the answer-time webhook already
wrote the row.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from twilio.request_validator import RequestValidator

from core.models import Conversation

CALLBACK_URL = reverse("api:twilio-voice-status-callback")


def _sign(url: str, params: dict, token: str) -> str:
    return RequestValidator(token).compute_signature(url, params)


@pytest.fixture()
def absolute_url() -> str:
    return f"http://testserver{CALLBACK_URL}"


@pytest.mark.django_db(transaction=True)
def test_returns_503_when_token_unset(client, settings):
    settings.TWILIO_AUTH_TOKEN = ""
    resp = client.post(
        CALLBACK_URL,
        {"From": "+14165550111", "CallStatus": "no-answer"},
    )
    assert resp.status_code == 503
    assert resp.json() == {"error": "not_configured"}
    assert Conversation.objects.filter(channel="phone").count() == 0


@pytest.mark.django_db(transaction=True)
def test_returns_403_on_tampered_signature(client, settings):
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    resp = client.post(
        CALLBACK_URL,
        {"From": "+14165550111", "CallStatus": "no-answer"},
        HTTP_X_TWILIO_SIGNATURE="obviously-wrong",
    )
    assert resp.status_code == 403
    assert Conversation.objects.filter(channel="phone").count() == 0


@pytest.mark.django_db(transaction=True)
def test_no_answer_creates_abandoned_conversation(client, settings, absolute_url):
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "+14165550111", "CallStatus": "no-answer", "CallSid": "CA-na"}
    sig = _sign(absolute_url, params, settings.TWILIO_AUTH_TOKEN)
    resp = client.post(CALLBACK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)

    assert resp.status_code == 200
    convs = Conversation.objects.filter(channel="phone")
    assert convs.count() == 1
    conv = convs.first()
    assert conv.status == "abandoned"
    assert conv.customer_identifier == "+14165550111"


@pytest.mark.django_db(transaction=True)
def test_completed_status_does_not_create_row(client, settings, absolute_url):
    """The answer-time webhook owns the ``completed`` row. This callback
    skips it so we don't double-write."""
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "+14165550111", "CallStatus": "completed", "CallSid": "CA-ok"}
    sig = _sign(absolute_url, params, settings.TWILIO_AUTH_TOKEN)
    resp = client.post(CALLBACK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)

    assert resp.status_code == 200
    assert Conversation.objects.filter(channel="phone").count() == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("status_value", ["busy", "failed", "canceled"])
def test_other_missed_statuses_also_create_row(client, settings, absolute_url, status_value):
    """``busy``, ``failed``, ``canceled`` all behave like ``no-answer``."""
    settings.TWILIO_AUTH_TOKEN = "tok-shhh"
    params = {"From": "+14165550222", "CallStatus": status_value, "CallSid": "CA-x"}
    sig = _sign(absolute_url, params, settings.TWILIO_AUTH_TOKEN)
    resp = client.post(CALLBACK_URL, params, HTTP_X_TWILIO_SIGNATURE=sig)

    assert resp.status_code == 200
    convs = Conversation.objects.filter(channel="phone", status="abandoned")
    assert convs.count() == 1
