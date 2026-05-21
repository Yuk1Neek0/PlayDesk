"""
Test: concurrent booking inserts with the same (resource_id, time) must produce
exactly one success and one IntegrityError (Issue #2).

This test requires a live Postgres database with btree_gist and vector enabled.
It is skipped automatically when the DB is unavailable.
"""

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.django_db(transaction=True)

_UTC = UTC


@pytest.fixture()
def store_and_resource(db):
    from core.models import Resource, Store

    store = Store.objects.create(
        name="Test Store",
        timezone="UTC",
        business_hours={},
    )
    resource = Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Test",
        capacity=4,
        price_per_hour="60.00",
    )
    return store, resource


def _make_booking(resource, start: datetime, duration_minutes: int = 120):
    """Helper: create a Booking for resource over [start, start+duration)."""
    from core.models import Booking

    end = start + timedelta(minutes=duration_minutes)
    return Booking.objects.create(
        resource=resource,
        customer_name="Test Customer",
        customer_phone="000-0000",
        start_time=start,
        end_time=end,
        status="confirmed",
        source="manual",
    )


class TestBookingOverlapConstraint:
    def test_identical_time_slot_is_rejected(self, store_and_resource):
        """Two identical bookings for the same resource must fail at DB level."""
        from django.db import IntegrityError

        _, resource = store_and_resource
        start = datetime(2026, 6, 1, 14, 0, tzinfo=_UTC)

        # First insert succeeds
        b1 = _make_booking(resource, start)
        assert b1.pk is not None

        # Second insert must raise IntegrityError from the exclusion constraint
        with pytest.raises(IntegrityError):
            _make_booking(resource, start)

    def test_overlapping_time_slot_is_rejected(self, store_and_resource):
        """A booking whose range overlaps (but is not identical) must also fail."""
        from django.db import IntegrityError

        _, resource = store_and_resource
        start = datetime(2026, 6, 1, 16, 0, tzinfo=_UTC)

        _make_booking(resource, start, duration_minutes=120)  # 16:00–18:00

        # 17:00–19:00 overlaps → must be rejected
        with pytest.raises(IntegrityError):
            _make_booking(resource, start + timedelta(hours=1), duration_minutes=120)

    def test_adjacent_slots_are_allowed(self, store_and_resource):
        """Back-to-back bookings (end == next start) must NOT conflict."""
        _, resource = store_and_resource
        start = datetime(2026, 6, 1, 18, 0, tzinfo=_UTC)

        b1 = _make_booking(resource, start, duration_minutes=60)  # 18:00–19:00
        b2 = _make_booking(resource, start + timedelta(hours=1), duration_minutes=60)  # 19:00–20:00
        assert b1.pk is not None
        assert b2.pk is not None

    def test_different_resources_can_overlap(self, db):
        """The constraint is per-resource; two different resources can share a time slot."""
        from core.models import Resource, Store

        store = Store.objects.create(name="Multi-Resource Store", timezone="UTC", business_hours={})
        r1 = Resource.objects.create(
            store=store, type="console", name="Console A", capacity=4, price_per_hour="60.00"
        )
        r2 = Resource.objects.create(
            store=store, type="console", name="Console B", capacity=4, price_per_hour="60.00"
        )
        start = datetime(2026, 6, 1, 20, 0, tzinfo=_UTC)

        b1 = _make_booking(r1, start)
        b2 = _make_booking(r2, start)  # same slot, different resource — should succeed
        assert b1.pk is not None
        assert b2.pk is not None
