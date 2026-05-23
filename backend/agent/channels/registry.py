"""Outbound adapter registry.

`get_outbound_adapter(channel)` returns the single adapter instance
registered under a channel name. Lazy-instantiated on first lookup so
importing the agent package never touches the Twilio SDK or any other
provider client.

Production registrations live here. Tests can call `register_outbound_adapter`
to wire in `LoggingOutboundAdapter` under either the `"test"` channel
(for direct registry-level assertions) or any other channel name (to
shadow the real adapter when exercising the sender command).
"""

from __future__ import annotations

from .outbound_base import OutboundChannelAdapter
from .twilio_sms_outbound import TwilioSmsOutboundAdapter

# Module-level singletons; instantiated lazily on first lookup.
_OUTBOUND_ADAPTERS: dict[str, OutboundChannelAdapter] = {}


def _bootstrap() -> None:
    """Register the built-in adapters once."""
    if _OUTBOUND_ADAPTERS:
        return
    _OUTBOUND_ADAPTERS[TwilioSmsOutboundAdapter.channel] = TwilioSmsOutboundAdapter()


def get_outbound_adapter(channel: str) -> OutboundChannelAdapter:
    """Look up the registered adapter for a channel.

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
