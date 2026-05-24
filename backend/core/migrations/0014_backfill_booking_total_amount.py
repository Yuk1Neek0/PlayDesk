"""Backfill ``Booking.total_amount`` from ``resource.price_per_hour * hours``.

v8 pricing-rules ships ``total_amount`` as nullable so this additive
migration can land cleanly. Every existing booking is backfilled here from
the per-hour rate; ``rule_snapshot`` stays at its default empty list (no
rules existed when these bookings were created). After this migration, the
field is guaranteed populated for every row in the table.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations


def _hours_between(start, end) -> Decimal:
    """Compute hours as Decimal without going through float."""
    seconds = int((end - start).total_seconds())
    # 1 second = Decimal(1) / Decimal(3600); use integer arithmetic to stay
    # exact.
    return (Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.0001"))


def backfill_total_amount(apps, schema_editor):
    Booking = apps.get_model("core", "Booking")
    rows = Booking.objects.select_related("resource").filter(total_amount__isnull=True)
    for booking in rows.iterator():
        rate = booking.resource.price_per_hour
        hours = _hours_between(booking.start_time, booking.end_time)
        booking.total_amount = (rate * hours).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        booking.save(update_fields=["total_amount"])


def noop_reverse(apps, schema_editor):
    """Backwards path is a no-op — total_amount has a sensible value either
    way and removing it isn't this migration's responsibility."""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_booking_pricing_fields"),
    ]

    operations = [
        migrations.RunPython(backfill_total_amount, noop_reverse),
    ]
