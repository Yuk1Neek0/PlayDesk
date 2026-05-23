"""
Thin send interface for campaigns.

`send_campaign_message(customer, body, reference)` is the *only* function
that talks to delivery. The implementation is picked at import time:

  - If `outbound.api.enqueue_message` is importable, the real impl delegates
    to it with template_key="campaign".
  - Otherwise a logging stub returns success so the audit pipeline still
    records the attempt and the epic ships independently of `outbound`.

Tests force either impl via the `force_send_impl` context manager so the
runner test can exercise both paths in one process.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str | None = None
    reason: str | None = None


SendImpl = Callable[..., SendResult]


def _real_impl_factory(enqueue_message) -> SendImpl:
    """Build the real impl that delegates to outbound.api.enqueue_message."""

    def _real(customer, body: str, reference: str) -> SendResult:
        msg = enqueue_message(
            customer,
            template_key="campaign",
            context={"body": body},
            channel="sms",
            reference=reference,
        )
        return SendResult(ok=True, provider_message_id=str(msg.id), reason=None)

    return _real


def _stub_impl(customer, body: str, reference: str) -> SendResult:
    """Logging stub used when `outbound` is not installed."""
    logger.info("[campaigns] stub send (outbound not installed): %s", reference)
    return SendResult(ok=True, provider_message_id=None, reason=None)


def _select_impl() -> SendImpl:
    try:
        from outbound.api import enqueue_message
    except ImportError:
        return _stub_impl
    return _real_impl_factory(enqueue_message)


# Module-level binding. Tests use force_send_impl() to swap.
_impl: SendImpl = _select_impl()


def _get_impl() -> SendImpl:
    """Expose the currently bound impl (test hook)."""
    return _impl


def send_campaign_message(customer, body: str, reference: str) -> SendResult:
    """Send `body` to `customer`. Returns a SendResult with ok / id / reason."""
    return _impl(customer, body, reference)


@contextmanager
def force_send_impl(impl: SendImpl):
    """Temporarily bind `impl` as the active send function.

    Used by tests that need to exercise both stub and real paths in the
    same process without reloading the module.
    """
    global _impl
    original = _impl
    _impl = impl
    try:
        yield
    finally:
        _impl = original
