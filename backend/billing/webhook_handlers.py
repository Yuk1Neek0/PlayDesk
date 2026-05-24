"""Per-event-type handlers for the Stripe webhook receiver.

Each handler is a pure function `(event_dict) -> None` so the receiver
(`billing.views.stripe_webhook`) can dispatch via the `HANDLERS` table.
Handlers are transaction-wrapped so a partial update is impossible.

Receipts (SMS + email) live in `billing.receipts` and are called from
the handlers — the receipts module isolates the v4 outbound + Django
mail dependencies so the test suite can patch them in one place.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction

from core.models import BookingStatus, PaymentStatus, Store

from . import receipts
from .models import Payment, PaymentKind, PaymentRowStatus

logger = logging.getLogger(__name__)


def _event_object(event: dict) -> dict:
    return (event.get("data") or {}).get("object") or {}


@transaction.atomic
def handle_payment_intent_succeeded(event: dict) -> None:
    """Capture-side success — flips Payment + Booking statuses."""
    obj = _event_object(event)
    intent_id = obj.get("id")
    if not intent_id:
        return
    charge_id = obj.get("latest_charge") or ""
    event_id = event.get("id")

    payment = (
        Payment.objects.filter(stripe_payment_intent_id=intent_id).order_by("-created_at").first()
    )
    if payment is None:
        logger.info("payment_intent.succeeded: no Payment for %s", intent_id)
        return

    Payment.objects.filter(pk=payment.pk).update(
        status=PaymentRowStatus.SUCCEEDED,
        stripe_charge_id=charge_id,
        stripe_event_id=event_id,
    )

    booking = payment.booking
    if payment.kind == PaymentKind.DEPOSIT:
        booking.payment_status = PaymentStatus.DEPOSIT_PAID
        booking.status = BookingStatus.CONFIRMED
        booking.save(update_fields=["payment_status", "status"])
    elif payment.kind == PaymentKind.BALANCE:
        booking.payment_status = PaymentStatus.PAID_IN_FULL
        booking.save(update_fields=["payment_status"])

    receipts.send_payment_receipt(booking, payment)


@transaction.atomic
def handle_payment_intent_failed(event: dict) -> None:
    obj = _event_object(event)
    intent_id = obj.get("id")
    event_id = event.get("id")
    if not intent_id:
        return
    payment = (
        Payment.objects.filter(stripe_payment_intent_id=intent_id).order_by("-created_at").first()
    )
    if payment is None:
        return
    Payment.objects.filter(pk=payment.pk).update(
        status=PaymentRowStatus.FAILED,
        stripe_event_id=event_id,
    )
    # Booking stays in pending_payment — sweep_pending_payments will reap.


@transaction.atomic
def handle_charge_refunded(event: dict) -> None:
    obj = _event_object(event)
    charge_id = obj.get("id")
    event_id = event.get("id")
    amount_refunded = Decimal(str(obj.get("amount_refunded", 0))) / Decimal("100")

    payment = Payment.objects.filter(stripe_charge_id=charge_id).order_by("-created_at").first()
    if payment is None:
        logger.info("charge.refunded: no Payment for charge %s", charge_id)
        return

    booking = payment.booking
    # Promote any provisional refund row (kind=refund, status=pending) for
    # this booking to succeeded; otherwise create one.
    existing_refund = (
        Payment.objects.filter(
            booking=booking,
            kind=PaymentKind.REFUND,
            status=PaymentRowStatus.PENDING,
        )
        .order_by("-created_at")
        .first()
    )
    if existing_refund is not None:
        Payment.objects.filter(pk=existing_refund.pk).update(
            status=PaymentRowStatus.SUCCEEDED,
            stripe_charge_id=charge_id,
            stripe_event_id=event_id,
        )
        refund_row = existing_refund
    else:
        refund_row = Payment.objects.create(
            store=booking.resource.store,
            booking=booking,
            kind=PaymentKind.REFUND,
            amount=-amount_refunded,
            currency=payment.currency,
            status=PaymentRowStatus.SUCCEEDED,
            stripe_charge_id=charge_id,
            stripe_event_id=event_id,
        )

    deposit = Decimal(booking.deposit_amount or 0)
    if amount_refunded >= deposit and deposit > 0:
        booking.payment_status = PaymentStatus.REFUNDED
    else:
        booking.payment_status = PaymentStatus.PARTIALLY_REFUNDED
    booking.save(update_fields=["payment_status"])

    receipts.send_refund_receipt(booking, refund_row)


@transaction.atomic
def handle_account_updated(event: dict) -> None:
    obj = _event_object(event)
    account_id = obj.get("id")
    if not account_id:
        return
    store = Store.objects.filter(stripe_account_id=account_id).first()
    if store is None:
        return
    Store.objects.filter(pk=store.pk).update(
        stripe_charges_enabled=bool(obj.get("charges_enabled", False)),
    )


HANDLERS = {
    "payment_intent.succeeded": handle_payment_intent_succeeded,
    "payment_intent.payment_failed": handle_payment_intent_failed,
    "charge.refunded": handle_charge_refunded,
    "account.updated": handle_account_updated,
}
