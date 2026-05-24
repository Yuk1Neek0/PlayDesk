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

    # Use values_list so any post-migration field added to Store (e.g. v7's
    # `cancellation_lead_hours`) doesn't get SELECT'd against a column the
    # schema doesn't yet have at this migration's apply time.
    points_by_store: dict[int, int] = {
        sid: int(ppb) for sid, ppb in Store.objects.values_list("id", "points_per_booking")
    }

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
        # Cross-slice dep: this data migration imports live `Store` (which
        # post-merge includes the outbound slice's `quiet_hours_*` columns).
        # Without this edge, the live-model SELECT runs against a Store
        # table missing those columns.
        ("core", "0008_store_quiet_hours_end_store_quiet_hours_start"),
    ]

    operations = [
        migrations.RunPython(_seed_backfill, reverse_code=_reverse_backfill),
    ]
