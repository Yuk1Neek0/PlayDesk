"""
Channel adapter abstraction.

The agent loop doesn't know whether a message arrived over HTTP/SSE,
SMS, WhatsApp, or a phone call. Each `ChannelAdapter` subclass owns the
translation between a channel's raw inbound payload and the
`NormalizedMessage` the loop consumes, and (where applicable) between
the loop's reply text and the channel's outbound wire format.

By design this module is pure Python — no Django imports — so adapters
can be reused outside the DRF view layer (e.g. a Celery worker
consuming SMS webhooks asynchronously).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class NormalizedMessage:
    """Channel-agnostic representation of one inbound message.

    `customer_identifier` is the stable identity for the conversation:
    a normalised phone for SMS / voice, a session id for web chat, etc.
    The adapter is responsible for normalising it (e.g. via
    `core.phone.normalize_phone` for phone-based channels).
    """

    text: str
    customer_identifier: str
    channel: str
    language: str | None = None
    rag_chunks: list[str] = field(default_factory=list)
    raw_payload: dict | None = None


class ChannelAdapter(ABC):
    """One adapter per inbound channel.

    Subclasses set the `channel` class var so the agent harness can pick
    the right adapter from a registry. The two methods describe the two
    sides of every channel:

    - `normalize_inbound` parses the channel's raw payload into a
      `NormalizedMessage`.
    - `format_outbound` produces the channel's response shape from the
      agent's assembled reply text. Streaming channels (e.g. web chat
      SSE) can return a no-op placeholder here — the streaming view
      handles framing itself.
    """

    channel: ClassVar[str]

    @abstractmethod
    def normalize_inbound(
        self,
        payload: dict,
        headers: Mapping[str, str] | None = None,
    ) -> NormalizedMessage:
        """Translate the channel's raw payload into a NormalizedMessage."""

    @abstractmethod
    def format_outbound(
        self,
        reply_text: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        """Translate the agent's reply text into the channel's wire format.

        Streaming channels can return a dict matching the SSE `done` event
        payload; one-shot channels (SMS, WhatsApp) typically return the
        channel's response body (e.g. TwiML for Twilio SMS).
        """
