"""Unit tests for OutboundChannelAdapter implementations — pure Python, no DB."""

from __future__ import annotations

import pytest

from agent.channels._test_helpers import LoggingOutboundAdapter
from agent.channels.outbound_base import OutboundChannelAdapter, OutboundSendResult
from agent.channels.registry import (
    get_outbound_adapter,
    register_outbound_adapter,
    unregister_outbound_adapter,
)
from agent.channels.twilio_sms_outbound import TwilioSmsOutboundAdapter


def test_abc_cannot_be_instantiated_without_send():
    """A subclass without `send()` must fail at instantiation time."""

    class Incomplete(OutboundChannelAdapter):
        channel = "broken"

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_twilio_outbound_returns_not_configured_when_creds_missing(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    result = TwilioSmsOutboundAdapter().send("+14165550001", "hello")
    assert isinstance(result, OutboundSendResult)
    assert result.ok is False
    assert result.reason == "not_configured"
    assert result.provider_message_id is None


def test_twilio_outbound_returns_not_configured_when_one_var_missing(monkeypatch):
    """Partial config is treated the same as no config — no half-sends."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth_test")
    monkeypatch.delenv("TWILIO_FROM_NUMBER", raising=False)
    result = TwilioSmsOutboundAdapter().send("+14165550001", "hi")
    assert result.ok is False
    assert result.reason == "not_configured"


def test_twilio_outbound_happy_path_returns_sid(monkeypatch):
    """Patch the Twilio SDK to assert the adapter forwards the SID."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth_test")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15555550000")

    captured: dict = {}

    class _FakeMessage:
        sid = "SM_fake_sid_123"

    class _FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeMessage()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    import twilio.rest

    monkeypatch.setattr(twilio.rest, "Client", _FakeClient)

    result = TwilioSmsOutboundAdapter().send("+14165550001", "hi there")
    assert result.ok is True
    assert result.provider_message_id == "SM_fake_sid_123"
    assert result.reason is None
    assert captured == {
        "to": "+14165550001",
        "from_": "+15555550000",
        "body": "hi there",
    }


def test_twilio_outbound_wraps_twilio_exception(monkeypatch):
    """A TwilioRestException must become a failed result, never raise."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth_test")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+15555550000")

    from twilio.base.exceptions import TwilioRestException

    class _BrokenMessages:
        def create(self, **kwargs):
            raise TwilioRestException(status=400, uri="/x", msg="bad number")

    class _BrokenClient:
        def __init__(self, *args, **kwargs):
            self.messages = _BrokenMessages()

    import twilio.rest

    monkeypatch.setattr(twilio.rest, "Client", _BrokenClient)

    result = TwilioSmsOutboundAdapter().send("+1notreal", "hi")
    assert result.ok is False
    assert result.provider_message_id is None
    assert result.reason is not None
    assert "twilio_error" in result.reason


def test_registry_returns_twilio_for_sms_channel():
    adapter = get_outbound_adapter("sms")
    assert isinstance(adapter, TwilioSmsOutboundAdapter)


def test_registry_raises_keyerror_for_unknown_channel():
    with pytest.raises(KeyError):
        get_outbound_adapter("no_such_channel")


def test_registry_supports_test_adapter_registration():
    LoggingOutboundAdapter.reset()
    register_outbound_adapter(LoggingOutboundAdapter())
    try:
        adapter = get_outbound_adapter("test")
        result = adapter.send("+14165550001", "from-test")
        assert result.ok is True
        assert LoggingOutboundAdapter.sent == [
            {"to": "+14165550001", "body": "from-test", "metadata": None}
        ]
    finally:
        unregister_outbound_adapter("test")
        LoggingOutboundAdapter.reset()


def test_outbound_send_result_dataclass_shape():
    """`OutboundSendResult` carries the three documented fields."""
    r = OutboundSendResult(ok=True, provider_message_id="SM1", reason=None)
    assert r.ok is True and r.provider_message_id == "SM1" and r.reason is None
    r2 = OutboundSendResult(ok=False, provider_message_id=None, reason="oops")
    assert r2.ok is False and r2.reason == "oops"
