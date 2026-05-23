"""Twilio SMS outbound adapter.

Wraps `twilio.rest.Client(...).messages.create(...)`. Reuses the same
env vars as the inbound adapter so there's one Twilio account to
configure. When credentials are absent, `send()` returns the canonical
`not_configured` result rather than raising — the CI suite stays green
without secrets and the `send_outbound` cron leaves the row queued.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .outbound_base import OutboundChannelAdapter, OutboundSendResult


class TwilioSmsOutboundAdapter(OutboundChannelAdapter):
    channel = "sms"

    def send(
        self,
        to_identifier: str,
        body: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> OutboundSendResult:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
        if not (account_sid and auth_token and from_number):
            return OutboundSendResult(ok=False, provider_message_id=None, reason="not_configured")

        # Import lazily so importing this module never pulls in the
        # Twilio SDK at module load — keeps `not_configured` deploys
        # from paying the import cost.
        from twilio.base.exceptions import TwilioRestException
        from twilio.rest import Client

        try:
            client = Client(account_sid, auth_token)
            msg = client.messages.create(
                to=to_identifier,
                from_=from_number,
                body=body,
            )
        except TwilioRestException as exc:
            return OutboundSendResult(
                ok=False, provider_message_id=None, reason=f"twilio_error: {exc}"
            )

        return OutboundSendResult(
            ok=True, provider_message_id=getattr(msg, "sid", None), reason=None
        )
