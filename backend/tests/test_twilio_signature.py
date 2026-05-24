"""Unit tests for the shared `verify_twilio_signature` helper.

The helper has no Django dependency, so the tests are plain pytest —
no DB, no client fixture.
"""

from __future__ import annotations

from twilio.request_validator import RequestValidator

from agent.channels.twilio_signature import verify_twilio_signature

_URL = "https://playdesk.example.com/api/webhooks/twilio/sms/"
_PARAMS = {"From": "+14165550111", "Body": "hi", "MessageSid": "SMabc"}
_TOKEN = "auth-token-shhh"


def _sign(params: dict, token: str = _TOKEN, url: str = _URL) -> str:
    return RequestValidator(token).compute_signature(url, params)


def test_returns_true_for_valid_signature():
    sig = _sign(_PARAMS)
    assert verify_twilio_signature(_URL, _PARAMS, sig, _TOKEN) is True


def test_returns_false_for_tampered_signature():
    """A swapped char in the signature must invalidate."""
    sig = _sign(_PARAMS)
    bad = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert verify_twilio_signature(_URL, _PARAMS, bad, _TOKEN) is False


def test_returns_false_when_params_differ():
    """Different params than were signed — common tampering case."""
    sig = _sign(_PARAMS)
    altered = dict(_PARAMS, Body="rewritten")
    assert verify_twilio_signature(_URL, altered, sig, _TOKEN) is False


def test_returns_false_when_token_empty():
    """An empty auth token always rejects — never accidentally trusts."""
    sig = _sign(_PARAMS)
    assert verify_twilio_signature(_URL, _PARAMS, sig, "") is False


def test_returns_false_when_signature_empty():
    assert verify_twilio_signature(_URL, _PARAMS, "", _TOKEN) is False


def test_accepts_mapping_not_only_dict():
    """The helper coerces Mapping to dict so e.g. Django's QueryDict works."""

    class FakeQueryDict(dict):
        pass

    params = FakeQueryDict(_PARAMS)
    sig = _sign(_PARAMS)
    assert verify_twilio_signature(_URL, params, sig, _TOKEN) is True
