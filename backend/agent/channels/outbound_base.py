"""Outbound channel adapter abstraction.

Mirror of the inbound `ChannelAdapter` in `base.py`, but for the
*outbound* direction: the agent picks a registered adapter by channel
name and calls `send()` to deliver one message. Adapters are pure
Python — no Django imports — so they're reusable from management
commands, cron jobs, and (eventually) async workers without a Django
session.

The two ABCs intentionally don't share an interface: the inbound side
parses webhook payloads into a `NormalizedMessage` and produces a
channel-specific wire response; the outbound side just takes a string
and writes it. Trying to unify them would mean a `Union`-typed mess.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass
class OutboundSendResult:
    """The single value an `OutboundChannelAdapter.send()` may return.

    `ok` is False when delivery did not happen. `reason` carries a short
    machine-readable label (`"not_configured"`, `"twilio_error"`, ...)
    that the sender command uses to decide between *retry-later* (leave
    the row queued) and *give-up* (mark failed). `provider_message_id`
    is the upstream SID — kept for traceability when staff inspect the
    customer's outbound log.
    """

    ok: bool
    provider_message_id: str | None = None
    reason: str | None = None


class OutboundChannelAdapter(ABC):
    """One adapter per outbound channel.

    Subclasses set the `channel` class var so the registry can pick the
    right adapter from a string (`"sms"`, `"web_chat"`, ...). The class
    var matches the inbound adapter's value so a future caller can ask
    "is there an outbound version of this inbound channel?" by string
    equality.
    """

    channel: ClassVar[str]

    @abstractmethod
    def send(
        self,
        to_identifier: str,
        body: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> OutboundSendResult:
        """Deliver one outbound message.

        `to_identifier` is the channel-specific recipient address — an
        E.164 phone for SMS, a session id for web chat, an email for
        a future email channel. Adapters must never raise on delivery
        failure; they return `OutboundSendResult(ok=False, reason=...)`
        so the sender can decide whether to retry or fail the row.
        """
