"""Cancel orphaned pending_payment bookings older than STRIPE_HOLD_MINUTES.

Distinct from the legacy `expire_holds` command (which targets
Booking.status='pending_payment'); this one operates on
`Booking.payment_status='pending_payment'` — the v9 ledger field.

Run hourly via cron / scheduler.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Cancel bookings stuck in payment_status='pending_payment' beyond the hold window."

    def handle(self, *args, **options) -> None:
        from billing.views import sweep_pending_payments

        n = sweep_pending_payments()
        self.stdout.write(f"Swept {n} stale pending-payment booking(s).")
