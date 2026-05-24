"""Unit tests for `TwilioWhatsAppOutboundAdapter` — pure Python, no DB."""

from __future__ import annotations

import pytest

from agent.channels.outbound_base import OutboundSendResult
from agent.channels.registry import get_outbound_adapter
from agent.channels.twilio_whatsapp_outbound import TwilioWhatsAppOutboundAdapter


def test_returns_not_configured_when_all_creds_missing(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_WHATSAPP_FROM", raising=False)
    result = TwilioWhatsAppOutboundAdapter().send("+14165550001", "hello")
    assert isinstance(result, OutboundSendResult)
    assert result.ok is False
    assert result.reason == "not_configured"
    assert result.provider_message_id is None


def test_returns_not_configured_when_whatsapp_from_missing(monkeypatch):
    """SID + token set, but no WhatsApp sender → still `not_configured`.

    Crucial because SMS env vars may be present in CI; the WhatsApp
    adapter must still degrade cleanly without its own sender number.
    """
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth_test")
    monkeypatch.delenv("TWILIO_WHATSAPP_FROM", raising=False)
    result = TwilioWhatsAppOutboundAdapter().send("+14165550001", "hi")
    assert result.ok is False
    assert result.reason == "not_configured"


def test_does_not_call_twilio_when_not_configured(monkeypatch):
    """No SDK calls happen on the not_configured path — proves laziness."""
    monkeypatch.delenv("TWILIO_WHATSAPP_FROM", raising=False)

    class _Boom:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Twilio client must not be constructed when not configured")

    import twilio.rest

    monkeypatch.setattr(twilio.rest, "Client", _Boom)
    result = TwilioWhatsAppOutboundAdapter().send("+14165550001", "hi")
    assert result.ok is False
    assert result.reason == "not_configured"


def test_happy_path_prefixes_addresses_with_whatsapp(monkeypatch):
    """Mocked Twilio success: both `from_` and `to` must carry `whatsapp:`."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth_test")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "+14155238886")

    captured: dict = {}

    class _FakeMessage:
        sid = "SM_whatsapp_sid_xyz"

    class _FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeMessage()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    import twilio.rest

    monkeypatch.setattr(twilio.rest, "Client", _FakeClient)

    result = TwilioWhatsAppOutboundAdapter().send("+14165550001", "hi there")
    assert result.ok is True
    assert result.provider_message_id == "SM_whatsapp_sid_xyz"
    assert result.reason is None
    assert captured == {
        "to": "whatsapp:+14165550001",
        "from_": "whatsapp:+14155238886",
        "body": "hi there",
    }


def test_happy_path_does_not_double_prefix(monkeypatch):
    """Tolerate operators who already put `whatsapp:` in env / DB."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth_test")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

    captured: dict = {}

    class _FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)

            class _M:
                sid = "SM1"

            return _M()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.messages = _FakeMessages()

    import twilio.rest

    monkeypatch.setattr(twilio.rest, "Client", _FakeClient)

    TwilioWhatsAppOutboundAdapter().send("whatsapp:+14165550001", "hi")
    assert captured["from_"] == "whatsapp:+14155238886"
    assert captured["to"] == "whatsapp:+14165550001"


def test_wraps_twilio_exception(monkeypatch):
    """A TwilioRestException must become a failed result, never raise."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "auth_test")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "+14155238886")

    from twilio.base.exceptions import TwilioRestException

    class _BrokenMessages:
        def create(self, **kwargs):
            raise TwilioRestException(status=400, uri="/x", msg="not a whatsapp number")

    class _BrokenClient:
        def __init__(self, *args, **kwargs):
            self.messages = _BrokenMessages()

    import twilio.rest

    monkeypatch.setattr(twilio.rest, "Client", _BrokenClient)

    result = TwilioWhatsAppOutboundAdapter().send("+1notreal", "hi")
    assert result.ok is False
    assert result.provider_message_id is None
    assert result.reason is not None
    assert "twilio_error" in result.reason


def test_registry_returns_whatsapp_outbound_adapter():
    adapter = get_outbound_adapter("whatsapp")
    assert isinstance(adapter, TwilioWhatsAppOutboundAdapter)
    assert adapter.channel == "whatsapp"


def test_registry_sms_unaffected_by_whatsapp_registration():
    """Adding the WhatsApp adapter must not perturb the SMS lookup."""
    from agent.channels.twilio_sms_outbound import TwilioSmsOutboundAdapter

    adapter = get_outbound_adapter("sms")
    assert isinstance(adapter, TwilioSmsOutboundAdapter)


def test_unknown_channel_still_raises_keyerror():
    with pytest.raises(KeyError):
        get_outbound_adapter("no_such_channel")
