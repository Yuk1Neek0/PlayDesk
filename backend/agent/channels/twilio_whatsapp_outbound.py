"""Twilio WhatsApp outbound adapter.

Near-mirror of `twilio_sms_outbound.py`: same Twilio SDK, same
graceful-degrade posture (`not_configured` rather than raising when
creds are absent). Two structural differences from SMS:

- Reads a separate `TWILIO_WHATSAPP_FROM` env var. Twilio requires a
  dedicated WhatsApp sender (the sandbox uses `+14155238886`).
- Prepends `whatsapp:` to both `from_` and `to` in the API call —
  Twilio routes WhatsApp messages by the prefix on the address.

Out-of-scope in v5: WhatsApp templates required outside the 24-hour
customer-initiated session window. Free-form messaging works inside
the window.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .outbound_base import OutboundChannelAdapter, OutboundSendResult


class TwilioWhatsAppOutboundAdapter(OutboundChannelAdapter):
    channel = "whatsapp"

    def send(
        self,
        to_identifier: str,
        body: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> OutboundSendResult:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        from_number = os.environ.get("TWILIO_WHATSAPP_FROM", "")
        if not (account_sid and auth_token and from_number):
            return OutboundSendResult(ok=False, provider_message_id=None, reason="not_configured")

        # Lazy SDK import — keeps `not_configured` deploys from paying
        # the import cost.
        from twilio.base.exceptions import TwilioRestException
        from twilio.rest import Client

        # Twilio addresses both sides of a WhatsApp send with the
        # `whatsapp:` prefix. Tolerate operators who already include
        # it in env / DB (don't double-prefix).
        from_addr = (
            from_number if from_number.startswith("whatsapp:") else f"whatsapp:{from_number}"
        )
        to_addr = (
            to_identifier if to_identifier.startswith("whatsapp:") else f"whatsapp:{to_identifier}"
        )

        try:
            client = Client(account_sid, auth_token)
            msg = client.messages.create(
                to=to_addr,
                from_=from_addr,
                body=body,
            )
        except TwilioRestException as exc:
            return OutboundSendResult(
                ok=False, provider_message_id=None, reason=f"twilio_error: {exc}"
            )

        return OutboundSendResult(
            ok=True, provider_message_id=getattr(msg, "sid", None), reason=None
        )
