"""
Property-based tests for the booking / availability time math.

The bugs in PR #40 (agent prompt + check_availability built UTC datetimes
that should have been store-local) were time-zone class defects: an
example-based suite never caught them because every fixture's clock matched
the buggy assumption. These tests assert the underlying invariants
*regardless of the store's timezone, the date, or the chosen window*.

Each Hypothesis example creates its own store + resource and deletes them
on exit, so examples never share DB state. We avoid DST-transition hours
(2–3am local) and midnight rollovers — those are real but separate edge
cases worth explicit, not random, coverage.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

_TIMEZONES = [
    "UTC",
    "America/Toronto",
    "America/Los_Angeles",
    "Europe/London",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Australia/Sydney",
    "Pacific/Honolulu",
]


def _store_local_to_utc(tz_name: str, y: int, m: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


def _hh_mm(h: int) -> str:
    return f"{h:02d}:00"


@contextmanager
def _isolated_resource(tz_name: str):
    """A fresh Store + Resource scoped to a single Hypothesis example."""
    from core.models import Booking, Resource, Store

    store = Store.objects.create(
        name=f"Property Store {uuid.uuid4().hex[:6]}",
        timezone=tz_name,
        business_hours={
            day: {"open": "00:00", "close": "23:59"}
            for day in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        },
    )
    resource = Resource.objects.create(
        store=store,
        type="console",
        name=f"PropResource-{uuid.uuid4().hex[:6]}",
        capacity=4,
        price_per_hour="40.00",
        metadata={},
    )
    try:
        yield resource
    finally:
        Booking.objects.filter(resource=resource).delete()
        resource.delete()
        store.delete()


def _make_booking(resource, start_utc: datetime, end_utc: datetime, cancelled: bool = False):
    from core.models import Booking, BookingSource, BookingStatus

    return Booking.objects.create(
        resource=resource,
        customer_name="Property Customer",
        customer_phone="000-0000",
        start_time=start_utc,
        end_time=end_utc,
        status=BookingStatus.CANCELLED if cancelled else BookingStatus.CONFIRMED,
        source=BookingSource.MANUAL,
    )


_tz_strategy = st.sampled_from(_TIMEZONES)
_date_strategy = st.dates(
    min_value=datetime(2026, 6, 2).date(),
    max_value=datetime(2026, 11, 30).date(),
)
_start_hour_strategy = st.integers(min_value=6, max_value=18)
_duration_strategy = st.integers(min_value=1, max_value=3)


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(tz_name=_tz_strategy, booking_date=_date_strategy, start_hour=_start_hour_strategy, duration_hours=_duration_strategy)
@pytest.mark.django_db(transaction=True)
def test_check_availability_sees_booking_at_same_local_window(
    db, tz_name: str, booking_date, start_hour: int, duration_hours: int
):
    """
    A booking inserted at store-local (start_hour, start_hour+duration) MUST
    cause check_availability to exclude that resource for the same store-local
    window — regardless of the store's timezone.
    """
    from agent_tools.schemas import CheckAvailabilityInput
    from agent_tools.tools import check_availability

    with _isolated_resource(tz_name) as resource:
        start_utc = _store_local_to_utc(
            tz_name, booking_date.year, booking_date.month, booking_date.day, start_hour
        )
        end_utc = start_utc + timedelta(hours=duration_hours)
        _make_booking(resource, start_utc, end_utc)

        end_hour = start_hour + duration_hours
        out = check_availability(
            CheckAvailabilityInput(
                resource_type="console",
                date=booking_date.isoformat(),
                time_range=(_hh_mm(start_hour), _hh_mm(end_hour)),
                party_size=1,
            )
        )

        available_ids = {slot.resource_id for slot in out.available}
        assert resource.pk not in available_ids, (
            f"booking at store-local {start_hour}:00–{end_hour}:00 in {tz_name} "
            f"failed to block check_availability for the same window "
            f"(returned: {available_ids})"
        )


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(tz_name=_tz_strategy, booking_date=_date_strategy, start_hour=_start_hour_strategy, duration_hours=_duration_strategy)
@pytest.mark.django_db(transaction=True)
def test_check_availability_is_free_strictly_after_booking(
    db, tz_name: str, booking_date, start_hour: int, duration_hours: int
):
    """
    A check_availability window that starts at the booking's end MUST
    report the resource as available (adjacency != overlap).
    """
    from agent_tools.schemas import CheckAvailabilityInput
    from agent_tools.tools import check_availability

    with _isolated_resource(tz_name) as resource:
        start_utc = _store_local_to_utc(
            tz_name, booking_date.year, booking_date.month, booking_date.day, start_hour
        )
        end_utc = start_utc + timedelta(hours=duration_hours)
        _make_booking(resource, start_utc, end_utc)

        # Strategy bounds keep booking_end_hour <= 21, so query_end <= 22.
        booking_end_hour = start_hour + duration_hours
        query_start = booking_end_hour
        query_end = query_start + 1

        out = check_availability(
            CheckAvailabilityInput(
                resource_type="console",
                date=booking_date.isoformat(),
                time_range=(_hh_mm(query_start), _hh_mm(query_end)),
                party_size=1,
            )
        )

        available_ids = {slot.resource_id for slot in out.available}
        assert resource.pk in available_ids, (
            f"adjacent window {query_start}:00–{query_end}:00 (booking ends "
            f"{booking_end_hour}:00) in {tz_name} was wrongly reported as taken"
        )


@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(tz_name=_tz_strategy, booking_date=_date_strategy, start_hour=_start_hour_strategy, duration_hours=_duration_strategy)
@pytest.mark.django_db(transaction=True)
def test_cancelled_booking_does_not_block(
    db, tz_name: str, booking_date, start_hour: int, duration_hours: int
):
    """A cancelled booking MUST NOT block availability in its old window."""
    from agent_tools.schemas import CheckAvailabilityInput
    from agent_tools.tools import check_availability

    with _isolated_resource(tz_name) as resource:
        start_utc = _store_local_to_utc(
            tz_name, booking_date.year, booking_date.month, booking_date.day, start_hour
        )
        end_utc = start_utc + timedelta(hours=duration_hours)
        _make_booking(resource, start_utc, end_utc, cancelled=True)

        end_hour = start_hour + duration_hours
        out = check_availability(
            CheckAvailabilityInput(
                resource_type="console",
                date=booking_date.isoformat(),
                time_range=(_hh_mm(start_hour), _hh_mm(end_hour)),
                party_size=1,
            )
        )

        available_ids = {slot.resource_id for slot in out.available}
        assert resource.pk in available_ids, (
            f"cancelled booking in {tz_name} still blocked check_availability"
        )
