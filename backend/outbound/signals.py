"""Booking-lifecycle signals that populate the outbound queue.

Wires four enqueue triggers + one cancellation cascade off `Booking`'s
`post_save`:

- **created**: `booking_confirmation` immediately + `reminder_24h` for
  `scheduled_at - 24h` (only if still in the future).
- **transition → no_show**: `no_show_followup` immediately.
- **transition → completed**: `booking_thank_you` immediately.
- **transition → cancelled**: bulk-cancel all queued rows whose
  `reference` starts with `"booking:<id>:"`.

`pre_save` stashes the prior status so `post_save` can detect a
transition (same pattern the retention slice uses for visit counters
in `core/signals.py`).

All handlers no-op when `booking.customer is None` — legacy rows
pre-dating the customer-FK backfill must not crash.

The string literals `"no_show"` and `"completed"` are intentional —
they aren't (yet) in `BookingStatus.choices` but Django's CharField
doesn't enforce choices at the DB layer, so staff workflows that flip
a booking to one of those values still trigger the right signal.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from core.models import Booking, BookingStatus

from .api import enqueue_message
from .models import OutboundMessage, OutboundStatus

# Sentinel for the "extra" transition statuses not yet in BookingStatus.choices.
_STATUS_NO_SHOW = "no_show"
_STATUS_COMPLETED = "completed"


def _booking_context(booking: Booking) -> dict:
    """Render context shared by all four templates.

    All four templates reference the same four placeholders, so one
    builder keeps them in sync.
    """
    customer = booking.customer
    return {
        "customer_name": (customer.name if customer else "") or "",
        "store_name": booking.resource.store.name,
        "start_time": booking.start_time.strftime("%Y-%m-%d %H:%M"),
        "resource_name": booking.resource.name,
    }


@receiver(pre_save, sender=Booking)
def _capture_prior_status_for_outbound(sender, instance: Booking, **kwargs) -> None:
    """Stash the pre-save status so post_save can detect transitions.

    Uses a distinct attribute name from the retention signal so the
    two slices don't collide.
    """
    if instance.pk is None:
        instance._outbound_prior_status = None
        return
    try:
        instance._outbound_prior_status = Booking.objects.only("status").get(pk=instance.pk).status
    except Booking.DoesNotExist:
        instance._outbound_prior_status = None


@receiver(post_save, sender=Booking)
def _enqueue_outbound_for_booking(sender, instance: Booking, created: bool, **kwargs) -> None:
    if instance.customer_id is None:
        return  # Legacy / unlinked booking — no SMS path possible.

    ctx = _booking_context(instance)

    if created:
        # Confirmation goes out immediately.
        enqueue_message(
            instance.customer,
            "booking_confirmation",
            ctx,
            reference=f"booking:{instance.id}:confirm",
        )
        # 24h reminder only if there's still ≥24h before start.
        reminder_at = instance.start_time - timedelta(hours=24)
        if reminder_at > timezone.now():
            enqueue_message(
                instance.customer,
                "reminder_24h",
                ctx,
                scheduled_for=reminder_at,
                reference=f"booking:{instance.id}:reminder_24h",
            )
        return

    # Existing row — fire one shot per transition into a terminal state.
    prior = getattr(instance, "_outbound_prior_status", None)
    new = instance.status
    if prior == new:
        return  # No transition — nothing to do.

    if new == _STATUS_NO_SHOW:
        enqueue_message(
            instance.customer,
            "no_show_followup",
            ctx,
            reference=f"booking:{instance.id}:no_show",
        )
    elif new == _STATUS_COMPLETED:
        enqueue_message(
            instance.customer,
            "booking_thank_you",
            ctx,
            reference=f"booking:{instance.id}:thank_you",
        )
    elif new == BookingStatus.CANCELLED:
        # Cascade: every queued reminder/confirmation for this booking
        # gets cancelled. Sent rows are left alone (already delivered).
        OutboundMessage.objects.filter(
            reference__startswith=f"booking:{instance.id}:",
            status=OutboundStatus.QUEUED,
        ).update(status=OutboundStatus.CANCELLED)
