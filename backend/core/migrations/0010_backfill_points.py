"""Seed PointTransaction rows for each existing Customer.

Gives every existing customer a starting balance equal to
``total_visits * store.points_per_booking``. Idempotent — skipped for
any customer that already has any PointTransaction row (re-running this
migration is a no-op). Reversible — removes only rows with
``source='backfill'`` AND ``reference='backfill-v4'``.

Calls ``award_points`` so the helper stays the only ledger-write path.
Live-model import inside a migration is safe here because both models
exist in the prior migration's state — this migration adds no schema.
"""

from __future__ import annotations

from django.db import migrations


def _seed_backfill(apps, schema_editor) -> None:
    # Use live models so `award_points` operates on real Customer instances.
    from core.memberships import award_points
    from core.models import Customer, PointTransaction, Store

    points_by_store: dict[int, int] = {s.id: int(s.points_per_booking) for s in Store.objects.all()}

    for customer in Customer.objects.all().only("id", "store_id", "total_visits"):
        if PointTransaction.objects.filter(customer_id=customer.id).exists():
            continue
        per_visit = points_by_store.get(customer.store_id, 10)
        delta = int(customer.total_visits) * per_visit
        if delta <= 0:
            continue
        award_points(customer, delta, "backfill", "backfill-v4")


def _reverse_backfill(apps, schema_editor) -> None:
    from core.models import PointTransaction

    PointTransaction.objects.filter(source="backfill", reference="backfill-v4").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_alter_booking_status"),
    ]

    operations = [
        migrations.RunPython(_seed_backfill, reverse_code=_reverse_backfill),
    ]
