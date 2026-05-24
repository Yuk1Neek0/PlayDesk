"""
Twilio WhatsApp inbound channel adapter.

Near-mirror of `twilio_sms.py`: Twilio's WhatsApp webhook posts the same
form-encoded body shape as SMS, except the `From` (and `To`) arrive as
`whatsapp:+E.164`. This adapter strips that `whatsapp:` prefix and then
runs the same phone-normalisation pipeline as SMS so the resulting
`customer_identifier` is a bare E.164 string — dedup-safe against
booking-resolved Customers.

Configuration:
- `TWILIO_AUTH_TOKEN` (env): consumed by the webhook view, not this
  adapter. The adapter itself is pure parsing.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape as _html_escape
from typing import Any

from core.phone import normalize_phone

from .base import ChannelAdapter, NormalizedMessage

# The prefix Twilio puts on WhatsApp `From`/`To` values. Stripped before
# we normalise the phone — `normalize_phone` expects bare E.164.
_WHATSAPP_PREFIX = "whatsapp:"


def _strip_whatsapp_prefix(raw: str) -> str:
    """Drop the leading `whatsapp:` from a Twilio WhatsApp address.

    Tolerant of mixed case and missing prefix (some test fixtures may
    pass a plain E.164).
    """
    if raw.lower().startswith(_WHATSAPP_PREFIX):
        return raw[len(_WHATSAPP_PREFIX) :]
    return raw


class TwilioWhatsAppAdapter(ChannelAdapter):
    channel = "whatsapp"

    def normalize_inbound(
        self,
        payload: dict,
        headers: Mapping[str, str] | None = None,
    ) -> NormalizedMessage:
        raw_from = str(payload.get("From", "")).strip()
        text = str(payload.get("Body", "")).strip()
        # Strip `whatsapp:` first, then normalise to E.164. Fall back to
        # the stripped value if normalisation fails — better to store
        # something than to drop the message.
        without_prefix = _strip_whatsapp_prefix(raw_from)
        normalised = normalize_phone(without_prefix) or without_prefix
        return NormalizedMessage(
            text=text,
            customer_identifier=normalised,
            channel=self.channel,
            raw_payload=payload,
        )

    def format_outbound(
        self,
        reply_text: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        """Return TwiML containing the assistant's reply.

        Twilio's WhatsApp endpoint accepts the same `<Response><Message>`
        TwiML shape as SMS — no media, no actions in v5.
        """
        safe = _html_escape(reply_text or "")
        return (
            f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'
        )
