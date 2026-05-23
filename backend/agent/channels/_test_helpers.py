"""Test-only outbound adapter — never imported by production code.

`LoggingOutboundAdapter` records every `send()` call on a class-level
list so tests can assert on what would have gone out without actually
sending anything. Lives in a `_test_helpers` module so a stray import
in production is immediately suspicious.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .outbound_base import OutboundChannelAdapter, OutboundSendResult


class LoggingOutboundAdapter(OutboundChannelAdapter):
    channel = "test"

    sent: list[dict[str, Any]] = []

    def send(
        self,
        to_identifier: str,
        body: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> OutboundSendResult:
        self.sent.append(
            {
                "to": to_identifier,
                "body": body,
                "metadata": dict(metadata) if metadata else None,
            }
        )
        return OutboundSendResult(ok=True, provider_message_id=f"log-{len(self.sent)}")

    @classmethod
    def reset(cls) -> None:
        cls.sent.clear()
