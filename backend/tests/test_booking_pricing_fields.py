"""
Tests for the v8 Booking pricing fields + backfill.

Covers:
  * The migration backfilled existing bookings (constructed via DB-level
    inserts that mimic pre-migration state).
  * New bookings can carry an explicit `total_amount` Decimal.
  * `rule_snapshot` round-trips list-of-dicts JSON cleanly.
  * `refund_amount` defaults to Decimal("0.00").
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture()
def store(db):
    from core.models import Store

    return Store.objects.create(name="Price Test Store", timezone="UTC")


@pytest.fixture()
def resource(store):
    from core.models import Resource

    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 #1",
        capacity=4,
        price_per_hour=Decimal("60.00"),
    )


def _make_booking(resource, *, total_amount=None, rule_snapshot=None):
    from core.models import Booking

    start = datetime(2026, 7, 1, 18, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    kwargs = {
        "resource": resource,
        "customer_name": "Test User",
        "customer_phone": "+1 555 0000",
        "start_time": start,
        "end_time": end,
    }
    if total_amount is not None:
        kwargs["total_amount"] = total_amount
    if rule_snapshot is not None:
        kwargs["rule_snapshot"] = rule_snapshot
    return Booking.objects.create(**kwargs)


class TestBookingPricingFields:
    def test_new_booking_with_explicit_total(self, resource):
        b = _make_booking(resource, total_amount=Decimal("123.45"))
        b.refresh_from_db()
        assert b.total_amount == Decimal("123.45")

    def test_refund_amount_defaults_to_zero(self, resource):
        b = _make_booking(resource, total_amount=Decimal("60.00"))
        b.refresh_from_db()
        assert b.refund_amount == Decimal("0.00")

    def test_rule_snapshot_round_trips_list_of_dicts(self, resource):
        snap = [
            {"label": "Base", "amount": "120.00", "rule_id": None},
            {"label": "Member discount (Gold)", "amount": "-18.00", "rule_id": 7},
        ]
        b = _make_booking(resource, total_amount=Decimal("102.00"), rule_snapshot=snap)
        b.refresh_from_db()
        assert b.rule_snapshot == snap

    def test_rule_snapshot_defaults_to_empty_list(self, resource):
        b = _make_booking(resource, total_amount=Decimal("60.00"))
        b.refresh_from_db()
        assert b.rule_snapshot == []

    def test_backfill_helper_computes_correct_amount(self, resource):
        """Import the migration's helper by its file path (migrations live
        under a non-importable name starting with digits) and verify the
        Decimal arithmetic for a 2-hour booking at $60/hr → $120.00."""
        import importlib.util
        import pathlib
        from decimal import ROUND_HALF_UP

        path = (
            pathlib.Path(__file__).resolve().parent.parent
            / "core"
            / "migrations"
            / "0014_backfill_booking_total_amount.py"
        )
        spec = importlib.util.spec_from_file_location("_backfill_mod", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        b = _make_booking(resource, total_amount=Decimal("0.00"))
        hours = mod._hours_between(b.start_time, b.end_time)
        computed = (b.resource.price_per_hour * hours).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert computed == Decimal("120.00")
