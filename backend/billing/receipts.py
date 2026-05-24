"""SMS + email receipt dispatch on Stripe events.

Isolated from `webhook_handlers` so tests can patch a single module to
verify dispatch without exercising the v4 outbound / Django mail
machinery end-to-end. All sends are best-effort — failures log + return
rather than raising (we don't want a flaky SMS provider to crash a
webhook handler).
"""

from __future__ import annotations

import logging

from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _enqueue(customer, template_key: str, context: dict, reference: str) -> None:
    try:
        from outbound.api import enqueue_message

        enqueue_message(
            customer=customer,
            template_key=template_key,
            context=context,
            reference=reference,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enqueue_message %s failed: %s", template_key, exc)


def _send_email(customer, subject: str, body: str) -> None:
    if customer is None or not customer.email:
        return
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=None,
            recipient_list=[customer.email],
            fail_silently=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("email send failed: %s", exc)


def send_payment_receipt(booking, payment) -> None:
    customer = booking.customer
    if customer is None:
        return
    amount = f"{payment.amount:.2f}"
    date = booking.start_time.date().isoformat()
    _enqueue(
        customer,
        "payment_receipt",
        {"amount": amount, "date": date},
        reference=f"receipt-{payment.pk}",
    )
    _send_email(
        customer,
        subject=f"PlayDesk payment receipt – ${amount}",
        body=(
            f"Hi {customer.name or 'there'},\n\n"
            f"We received ${amount} for your booking on {date}.\n"
            f"Booking #{booking.pk}\n\nThank you!\nPlayDesk"
        ),
    )


def send_refund_receipt(booking, refund_payment) -> None:
    customer = booking.customer
    if customer is None:
        return
    # refund payments are stored with negative amount; show the abs value
    amount = f"{abs(refund_payment.amount):.2f}"
    _enqueue(
        customer,
        "refund_receipt",
        {"amount": amount},
        reference=f"refund-receipt-{refund_payment.pk}",
    )
    _send_email(
        customer,
        subject=f"PlayDesk refund issued – ${amount}",
        body=(
            f"Hi {customer.name or 'there'},\n\n"
            f"We've issued a refund of ${amount} to your card. "
            f"Funds typically arrive in 5–10 business days.\n\n"
            f"Booking #{booking.pk}\n\nThank you!\nPlayDesk"
        ),
    )
