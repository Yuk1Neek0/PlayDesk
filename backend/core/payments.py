"""
Stripe payment gateway for booking deposits (test mode).

A thin wrapper around the Stripe SDK so the agent tool, the webhook view,
and the test suite depend on these functions rather than ``stripe.*``
directly. When ``STRIPE_SECRET_KEY`` is unset (CI, local dev without
Stripe) session creation is a no-op — the booking is still made, just
without a payment hold.
"""

from __future__ import annotations

from typing import Any

import stripe
from django.conf import settings


def create_checkout_session(booking: Any) -> str | None:
    """
    Open a Stripe Checkout session (test mode) for *booking*'s deposit.

    The booking id travels in the session ``metadata`` so the webhook can
    flip the right booking to ``confirmed`` once payment completes. Returns
    the hosted Checkout URL, or ``None`` when Stripe is not configured.
    """
    if not settings.STRIPE_SECRET_KEY:
        return None

    stripe.api_key = settings.STRIPE_SECRET_KEY
    hours = (booking.end_time - booking.start_time).total_seconds() / 3600
    amount_fen = max(1, int(float(booking.resource.price_per_hour) * hours * 100))

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": "cny",
                    "product_data": {
                        "name": f"PlayDesk booking #{booking.pk} — {booking.resource.name}",
                    },
                    "unit_amount": amount_fen,
                },
                "quantity": 1,
            }
        ],
        metadata={"booking_id": str(booking.pk)},
        success_url=settings.STRIPE_SUCCESS_URL,
        cancel_url=settings.STRIPE_CANCEL_URL,
    )
    return session.url


def verify_webhook_event(payload: bytes, signature: str) -> dict:
    """
    Verify a Stripe webhook signature and return the parsed event.

    Raises ``ValueError`` when the signature or payload is invalid — any
    failure means the request must be rejected.
    """
    try:
        return stripe.Webhook.construct_event(
            payload, signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid Stripe webhook: {exc}") from exc
