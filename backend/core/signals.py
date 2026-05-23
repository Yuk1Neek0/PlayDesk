"""
Signals that keep Customer denormalised counters in sync with Booking state.

Why a signal and not an aggregate-on-read: list views over Customer (the
admin /customers page in particular) need to render `total_visits` and
`last_visit_at` per row without a per-row aggregate. A signal trades a
small write cost on booking changes for one SELECT on read.

Rules:
- A "visit" is a booking whose status is anything other than CANCELLED.
- Creating a non-cancelled booking increments total_visits and bumps
  last_visit_at to the booking's start_time (if it's newer).
- Cancelling a previously-counted booking decrements total_visits.
- Re-confirming a previously-cancelled booking re-increments (no
  over-counting because the signal compares pre_save vs post_save status).
- Bookings with customer_id IS NULL are skipped silently (legacy rows
  pre-backfill, or rows that bypassed resolve_customer for any reason).
"""

from __future__ import annotations

from django.db.models import F
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import Booking, BookingStatus, Customer


def _is_visit(status: str) -> bool:
    """A booking counts toward total_visits unless it's been cancelled."""
    return status != BookingStatus.CANCELLED


def _bump_last_visit(customer_id: int, start_time) -> None:
    """Bump Customer.last_visit_at if the new start_time is newer."""
    Customer.objects.filter(pk=customer_id, last_visit_at__lt=start_time).update(
        last_visit_at=start_time
    )
    # Fill in if previously NULL.
    Customer.objects.filter(pk=customer_id, last_visit_at__isnull=True).update(
        last_visit_at=start_time
    )


@receiver(pre_save, sender=Booking)
def _capture_prior_status(sender, instance: Booking, **kwargs) -> None:
    """Stash the pre-save status so post_save can detect transitions."""
    if instance.pk is None:
        instance._prior_status = None
    else:
        try:
            instance._prior_status = Booking.objects.only("status").get(pk=instance.pk).status
        except Booking.DoesNotExist:
            instance._prior_status = None


@receiver(post_save, sender=Booking)
def _update_customer_counters(sender, instance: Booking, created: bool, **kwargs) -> None:
    if instance.customer_id is None:
        return  # Legacy / unlinked booking — nothing to maintain.

    prior = getattr(instance, "_prior_status", None)
    now_visit = _is_visit(instance.status)

    if created:
        if now_visit:
            Customer.objects.filter(pk=instance.customer_id).update(
                total_visits=F("total_visits") + 1
            )
            _bump_last_visit(instance.customer_id, instance.start_time)
        return

    # Existing row — check for a status transition that flips visit-ness.
    was_visit = _is_visit(prior) if prior is not None else now_visit
    if was_visit and not now_visit:
        Customer.objects.filter(pk=instance.customer_id, total_visits__gt=0).update(
            total_visits=F("total_visits") - 1
        )
    elif not was_visit and now_visit:
        Customer.objects.filter(pk=instance.customer_id).update(total_visits=F("total_visits") + 1)
        _bump_last_visit(instance.customer_id, instance.start_time)


@receiver(post_delete, sender=Booking)
def _decrement_on_delete(sender, instance: Booking, **kwargs) -> None:
    """If a non-cancelled booking is hard-deleted, undo its visit credit."""
    if instance.customer_id is None or not _is_visit(instance.status):
        return
    Customer.objects.filter(pk=instance.customer_id, total_visits__gt=0).update(
        total_visits=F("total_visits") - 1
    )
