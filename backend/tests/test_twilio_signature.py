"""Tests for the shared Twilio signature verifier.

Covers signed-OK / tampered-bad / empty-token-bad so every adapter that
reuses ``verify_twilio_signature`` (SMS, WhatsApp, Voice) inherits the same
contract.
"""

from __future__ import annotations

from twilio.request_validator import RequestValidator

from agent.channels.twilio_signature import verify_twilio_signature

_URL = "https://example.com/api/webhooks/twilio/voice/"
_PARAMS = {"From": "+14165550111", "CallSid": "CA1234567890"}
_TOKEN = "tok-shhh"


def _sign(url: str, params: dict, token: str) -> str:
    return RequestValidator(token).compute_signature(url, params)


def test_valid_signature_returns_true():
    sig = _sign(_URL, _PARAMS, _TOKEN)
    assert verify_twilio_signature(_URL, _PARAMS, sig, _TOKEN) is True


def test_tampered_signature_returns_false():
    assert verify_twilio_signature(_URL, _PARAMS, "deadbeef", _TOKEN) is False


def test_empty_token_returns_false_even_with_anything_passed():
    # Defensive: a missing auth token must short-circuit to False rather
    # than calling into the Twilio SDK (which would also fail, but less
    # explicitly).
    sig = _sign(_URL, _PARAMS, _TOKEN)
    assert verify_twilio_signature(_URL, _PARAMS, sig, "") is False


def test_empty_signature_returns_false():
    assert verify_twilio_signature(_URL, _PARAMS, "", _TOKEN) is False
