"""Thin Stripe SDK accessor for the billing app.

Every view in this app calls `get_stripe()` rather than importing the
`stripe` module directly so the secret key gets injected lazily — that
keeps tests free to omit credentials and lets the dashboard report
"Stripe not configured" cleanly when keys are unset.

`is_configured()` is the single source of truth for "do we have a real
secret"; views use it to decide whether to 503-degrade or to call the API.
"""

from __future__ import annotations

import logging
import os

import stripe as _stripe
from django.conf import settings

logger = logging.getLogger(__name__)


def _key() -> str:
    """Read the Stripe secret key from settings then live env.

    The env-fallback lets a user drop `STRIPE_SECRET_KEY` into `.env`
    after the Django process started without restart (matters for the
    dev loop). Settings still wins so tests can `override_settings`.
    """
    return settings.STRIPE_SECRET_KEY or os.environ.get("STRIPE_SECRET_KEY", "")


def _test_mode() -> bool:
    raw = os.environ.get("STRIPE_TEST_MODE", "True")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def is_configured() -> bool:
    """True iff a non-placeholder Stripe secret is available."""
    key = _key()
    return bool(key) and not key.endswith("...")


def get_stripe():
    """Return the `stripe` module with `api_key` set when configured.

    Returns the module unconditionally so callers can still type
    `stripe.PaymentIntent.create` — but if `is_configured()` is False
    the caller should short-circuit before calling out (or accept a
    `stripe.error.AuthenticationError`).
    """
    if is_configured():
        _stripe.api_key = _key()
    return _stripe


def degraded() -> bool:
    """Stripe not configured AND we're not in test mode → must 503.

    Test mode degrades to a no-op (returns None URLs etc.); live mode
    without a key is a configuration error and must surface to the
    operator instead of silently dropping payments.
    """
    return not is_configured() and not _test_mode()
