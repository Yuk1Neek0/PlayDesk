"""Unit tests for `TwilioWhatsAppAdapter` — pure Python, no DB."""

from __future__ import annotations

from agent.channels.base import NormalizedMessage
from agent.channels.registry import get_inbound_adapter
from agent.channels.twilio_whatsapp import TwilioWhatsAppAdapter


def test_normalize_inbound_strips_whatsapp_prefix():
    """`whatsapp:+E.164` becomes a bare E.164 customer_identifier."""
    msg = TwilioWhatsAppAdapter().normalize_inbound(
        {"From": "whatsapp:+14165550111", "Body": "hi"},
    )
    assert isinstance(msg, NormalizedMessage)
    assert msg.customer_identifier == "+14165550111"
    assert msg.channel == "whatsapp"
    assert msg.text == "hi"


def test_normalize_inbound_preserves_chinese_body_verbatim():
    """Non-ASCII bodies (Chinese) must round-trip without mangling."""
    body = "你好，今晚有 PS5 空闲吗？"
    msg = TwilioWhatsAppAdapter().normalize_inbound(
        {"From": "whatsapp:+14165550111", "Body": body},
    )
    assert msg.text == body


def test_normalize_inbound_handles_messy_formatted_phone():
    """Twilio sometimes posts the number with spaces — normalisation cleans it."""
    msg = TwilioWhatsAppAdapter().normalize_inbound(
        {"From": "whatsapp:+1 (416) 555-0111", "Body": "ok"},
    )
    assert msg.customer_identifier == "+14165550111"


def test_normalize_inbound_tolerates_missing_prefix():
    """A payload without the `whatsapp:` prefix still parses cleanly."""
    msg = TwilioWhatsAppAdapter().normalize_inbound(
        {"From": "+14165550111", "Body": "hi"},
    )
    assert msg.customer_identifier == "+14165550111"
    assert msg.channel == "whatsapp"


def test_normalize_inbound_stores_raw_payload():
    """Raw payload is kept for traceability."""
    payload = {"From": "whatsapp:+14165550111", "Body": "x", "MessageSid": "MSabc"}
    msg = TwilioWhatsAppAdapter().normalize_inbound(payload)
    assert msg.raw_payload == payload


def test_format_outbound_returns_valid_twiml_containing_text():
    out = TwilioWhatsAppAdapter().format_outbound("hello")
    assert isinstance(out, str)
    assert "<Response>" in out
    assert "<Message>" in out
    assert "hello" in out


def test_format_outbound_escapes_html_special_chars():
    """Avoid breaking the XML when the reply contains `<` / `&`."""
    out = TwilioWhatsAppAdapter().format_outbound("a < b & c")
    assert "&lt;" in out
    assert "&amp;" in out


def test_format_outbound_handles_empty_reply():
    """Empty reply still produces well-formed TwiML."""
    out = TwilioWhatsAppAdapter().format_outbound("")
    assert "<Response><Message></Message></Response>" in out


def test_registry_returns_whatsapp_inbound_adapter():
    """`get_inbound_adapter("whatsapp")` resolves to the WhatsApp class."""
    adapter = get_inbound_adapter("whatsapp")
    assert isinstance(adapter, TwilioWhatsAppAdapter)
    assert adapter.channel == "whatsapp"
