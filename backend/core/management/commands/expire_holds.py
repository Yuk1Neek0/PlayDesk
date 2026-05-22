"""
Expire stale pending-payment booking holds.

A booking created by the agent sits in ``pending_payment`` until its Stripe
deposit is paid (the webhook then flips it to ``confirmed``). If payment
never arrives, this command reaps the hold after ``STRIPE_HOLD_MINUTES``.

Holds are *deleted* rather than cancelled: the overlap-exclusion constraint
blocks even cancelled rows, so deleting is the only way to actually free the
slot for the next customer — and an unpaid hold was never a real booking.

Run periodically (cron / scheduler):  python manage.py expire_holds
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Booking, BookingStatus


class Command(BaseCommand):
    help = "Delete pending_payment bookings older than STRIPE_HOLD_MINUTES."

    def handle(self, *args, **options) -> None:
        cutoff = timezone.now() - timedelta(minutes=settings.STRIPE_HOLD_MINUTES)
        deleted, _ = Booking.objects.filter(
            status=BookingStatus.PENDING_PAYMENT,
            created_at__lt=cutoff,
        ).delete()
        self.stdout.write(f"Expired {deleted} stale pending-payment hold(s).")
