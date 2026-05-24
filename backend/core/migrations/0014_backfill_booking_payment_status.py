"""Backfill payment_status on bookings created before the v9 billing slice.

Existing rows already get `payment_status='not_required'` from the field
default, but applying the default at row-load time can leave the column
as NULL on databases that pre-existed the migration on a non-default
backend. This explicit RunPython makes the backfill deterministic and
visible to ops.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import migrations


def _backfill(apps, schema_editor):
    Booking = apps.get_model("core", "Booking")
    Booking.objects.filter(payment_status="").update(payment_status="not_required")
    Booking.objects.filter(deposit_amount__isnull=True).update(deposit_amount=Decimal("0.00"))


def _noop(apps, schema_editor):
    # Forward-only: there's nothing to "un-backfill".
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_billing_fields"),
    ]

    operations = [
        migrations.RunPython(_backfill, _noop),
    ]
