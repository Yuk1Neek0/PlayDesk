"""
Twilio SMS channel adapter.

Translates Twilio's `application/x-www-form-urlencoded` inbound webhook
payload into a `NormalizedMessage` and produces a TwiML response for
the assistant's reply.

Configuration:
- `TWILIO_AUTH_TOKEN` (env): required for signature verification — the
  view that wraps this adapter returns `503 not_configured` when it is
  missing, so CI without secrets stays green.

Phone identity:
- Inbound `From` is normalised via `core.phone.normalize_phone` so the
  customer_identifier dedups against booking-resolved Customers (the
  retention slice's contract).
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape as _html_escape
from typing import Any

from core.phone import normalize_phone

from .base import ChannelAdapter, NormalizedMessage


class TwilioSmsAdapter(ChannelAdapter):
    channel = "sms"

    def normalize_inbound(
        self,
        payload: dict,
        headers: Mapping[str, str] | None = None,
    ) -> NormalizedMessage:
        # Twilio's webhook posts a form body with `From`, `Body`,
        # `MessageSid`, etc. Treat the dict as already-decoded form data.
        raw_from = str(payload.get("From", "")).strip()
        text = str(payload.get("Body", "")).strip()
        # Fall back to the raw From when normalisation fails — better to
        # store something than to drop the message.
        normalised = normalize_phone(raw_from) or raw_from
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

        Twilio expects `application/xml`. We use a minimal `<Response>`
        with a single `<Message>` — no media, no actions. Long replies
        are not split here; Twilio splits SMS at the carrier level.
        """
        safe = _html_escape(reply_text or "")
        return (
            f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'
        )
