"""Channel adapter registries — inbound and outbound.

Two parallel registries keyed by channel name:

- `get_inbound_adapter(channel)` returns the `ChannelAdapter` that
  parses webhook payloads for that channel.
- `get_outbound_adapter(channel)` returns the `OutboundChannelAdapter`
  that delivers one outbound message over that channel.

Both are lazy-instantiated singletons so importing the agent package
never touches any provider SDK.

Production registrations live here. Tests can call
`register_outbound_adapter` to wire in `LoggingOutboundAdapter` under
either the `"test"` channel (for direct registry-level assertions) or
any other channel name (to shadow the real adapter when exercising the
sender command).
"""

from __future__ import annotations

from .base import ChannelAdapter
from .outbound_base import OutboundChannelAdapter
from .twilio_sms import TwilioSmsAdapter
from .twilio_sms_outbound import TwilioSmsOutboundAdapter
from .twilio_whatsapp import TwilioWhatsAppAdapter

# Module-level singletons; instantiated lazily on first lookup.
_INBOUND_ADAPTERS: dict[str, ChannelAdapter] = {}
_OUTBOUND_ADAPTERS: dict[str, OutboundChannelAdapter] = {}


def _bootstrap() -> None:
    """Register the built-in adapters once."""
    if not _INBOUND_ADAPTERS:
        _INBOUND_ADAPTERS[TwilioSmsAdapter.channel] = TwilioSmsAdapter()
        _INBOUND_ADAPTERS[TwilioWhatsAppAdapter.channel] = TwilioWhatsAppAdapter()
    if not _OUTBOUND_ADAPTERS:
        _OUTBOUND_ADAPTERS[TwilioSmsOutboundAdapter.channel] = TwilioSmsOutboundAdapter()


def get_inbound_adapter(channel: str) -> ChannelAdapter:
    """Look up the registered inbound adapter for a channel.

    Raises `KeyError` for an unknown channel — webhook views want to
    fail loudly rather than silently dropping a payload.
    """
    _bootstrap()
    return _INBOUND_ADAPTERS[channel]


def get_outbound_adapter(channel: str) -> OutboundChannelAdapter:
    """Look up the registered outbound adapter for a channel.

    Raises `KeyError` for an unknown channel — the caller almost always
    wants to fail loudly rather than silently dropping the message.
    """
    _bootstrap()
    return _OUTBOUND_ADAPTERS[channel]


def register_outbound_adapter(adapter: OutboundChannelAdapter) -> None:
    """Add or override an adapter under its own `channel` name.

    Tests use this to swap in `LoggingOutboundAdapter`; production code
    never needs to call it.
    """
    _bootstrap()
    _OUTBOUND_ADAPTERS[adapter.channel] = adapter


def unregister_outbound_adapter(channel: str) -> None:
    """Remove a registration. Tests use this to restore the default."""
    _OUTBOUND_ADAPTERS.pop(channel, None)
