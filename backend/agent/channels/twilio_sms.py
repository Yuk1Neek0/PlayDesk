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

Opt-out:
- When the body normalises to STOP / UNSUBSCRIBE / 退订 (case-insensitive),
  the adapter sets the `sms_opt_out` tag on the matching `Customer` row
  (deduped) so the outbound sender skips them. The agent loop still runs
  on the same message so the inbound webhook can still emit a final
  "you've been unsubscribed" reply via the existing path.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape as _html_escape
from typing import Any

from core.phone import normalize_phone

from .base import ChannelAdapter, NormalizedMessage

# Case-insensitive, trimmed body that flips a customer to opted-out.
_STOP_BODIES: frozenset[str] = frozenset({"stop", "unsubscribe", "退订"})


def _maybe_set_opt_out(normalised_phone: str, body: str) -> None:
    """If `body` is an opt-out keyword, add `sms_opt_out` to the customer's tags.

    Best-effort: silently no-ops if no `Customer` row matches the phone
    (a stranger texts STOP — we don't proactively create a customer just
    to mark them opted out).
    """
    keyword = body.strip().lower()
    if keyword not in _STOP_BODIES:
        return
    # Local import to keep this module Django-free at import time.
    from core.models import Customer

    for customer in Customer.objects.filter(phone=normalised_phone):
        tags = list(customer.tags or [])
        if "sms_opt_out" in tags:
            continue
        tags.append("sms_opt_out")
        customer.tags = tags
        customer.save(update_fields=["tags"])


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
        # Opt-out side-effect: STOP / UNSUBSCRIBE / 退订 sets the tag on
        # the customer (if one exists for this phone).
        _maybe_set_opt_out(normalised, text)
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
