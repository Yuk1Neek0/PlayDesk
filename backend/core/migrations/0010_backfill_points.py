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
    # Schema-sensitive: when running as a migration (`apps` provided),
    # use the historical Store/Customer state to avoid SELECT'ing
    # columns added by later migrations (e.g. v9 billing fields).
    # When called directly from a test (`apps is None`), fall back to
    # live models — that path always runs against a fully-migrated DB.
    from core.memberships import award_points
    from core.models import Customer as LiveCustomer
    from core.models import PointTransaction as LivePT
    from core.models import Store as LiveStore

    if apps is not None:
        StoreModel = apps.get_model("core", "Store")
        CustomerModel = apps.get_model("core", "Customer")
        PTModel = apps.get_model("core", "PointTransaction")
    else:
        StoreModel = LiveStore
        CustomerModel = LiveCustomer
        PTModel = LivePT

    points_by_store: dict[int, int] = {
        s["id"]: int(s["points_per_booking"])
        for s in StoreModel.objects.all().values("id", "points_per_booking")
    }

    for hist_customer in CustomerModel.objects.all().only("id", "store_id", "total_visits"):
        if PTModel.objects.filter(customer_id=hist_customer.id).exists():
            continue
        per_visit = points_by_store.get(hist_customer.store_id, 10)
        delta = int(hist_customer.total_visits) * per_visit
        if delta <= 0:
            continue
        live_customer = LiveCustomer.objects.get(pk=hist_customer.pk)
        award_points(live_customer, delta, "backfill", "backfill-v4")


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
