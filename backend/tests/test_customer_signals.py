"""Tests for the Booking → Customer counter signals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.models import Booking, BookingSource, BookingStatus, Customer, Resource, Store


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Counter Store", timezone="UTC", business_hours={})


@pytest.fixture()
def resource(store):
    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5",
        capacity=4,
        price_per_hour="40.00",
        metadata={},
    )


@pytest.fixture()
def customer(store):
    return Customer.objects.create(store=store, phone="+14165550111", name="Alice")


def _make_booking(
    resource, customer, start: datetime, status: str = BookingStatus.CONFIRMED
) -> Booking:
    return Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        start_time=start,
        end_time=start + timedelta(hours=1),
        status=status,
        source=BookingSource.MANUAL,
    )


@pytest.mark.django_db(transaction=True)
def test_create_confirmed_booking_increments_visits(resource, customer):
    assert customer.total_visits == 0
    _make_booking(resource, customer, datetime(2026, 10, 1, 18, tzinfo=UTC))
    customer.refresh_from_db()
    assert customer.total_visits == 1
    assert customer.last_visit_at == datetime(2026, 10, 1, 18, tzinfo=UTC)


@pytest.mark.django_db(transaction=True)
def test_cancel_decrements_visits(resource, customer):
    booking = _make_booking(resource, customer, datetime(2026, 10, 2, 18, tzinfo=UTC))
    customer.refresh_from_db()
    assert customer.total_visits == 1

    booking.status = BookingStatus.CANCELLED
    booking.save()
    customer.refresh_from_db()
    assert customer.total_visits == 0


@pytest.mark.django_db(transaction=True)
def test_reconfirm_after_cancel_does_not_double_count(resource, customer):
    booking = _make_booking(resource, customer, datetime(2026, 10, 3, 18, tzinfo=UTC))
    booking.status = BookingStatus.CANCELLED
    booking.save()
    customer.refresh_from_db()
    assert customer.total_visits == 0

    booking.status = BookingStatus.CONFIRMED
    booking.save()
    customer.refresh_from_db()
    assert customer.total_visits == 1  # not 2


@pytest.mark.django_db(transaction=True)
def test_null_customer_booking_is_skipped(resource):
    """A legacy booking with no customer must not crash the signal."""
    Booking.objects.create(
        resource=resource,
        customer=None,
        customer_name="Legacy",
        customer_phone="+14165550999",
        start_time=datetime(2026, 10, 4, 18, tzinfo=UTC),
        end_time=datetime(2026, 10, 4, 19, tzinfo=UTC),
        status=BookingStatus.CONFIRMED,
        source=BookingSource.MANUAL,
    )
    # No exception — implicit assertion.


@pytest.mark.django_db(transaction=True)
def test_last_visit_at_keeps_the_newest(resource, customer):
    """Two bookings: last_visit_at reflects the later start_time."""
    _make_booking(resource, customer, datetime(2026, 10, 5, 18, tzinfo=UTC))
    _make_booking(resource, customer, datetime(2026, 10, 6, 18, tzinfo=UTC))
    customer.refresh_from_db()
    assert customer.total_visits == 2
    assert customer.last_visit_at == datetime(2026, 10, 6, 18, tzinfo=UTC)


@pytest.mark.django_db(transaction=True)
def test_delete_decrements_visits(resource, customer):
    booking = _make_booking(resource, customer, datetime(2026, 10, 7, 18, tzinfo=UTC))
    customer.refresh_from_db()
    assert customer.total_visits == 1
    booking.delete()
    customer.refresh_from_db()
    assert customer.total_visits == 0
