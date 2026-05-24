"""Tests for the `auto_complete_checked_in` sweeper command (v10b)."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Booking, BookingStatus, Customer, Resource, Store
from outbound.models import OutboundMessage

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Sweeper Store", timezone="UTC", business_hours={})


@pytest.fixture()
def other_store(db):
    return Store.objects.create(name="Other Sweeper Store", timezone="UTC", business_hours={})


@pytest.fixture()
def resource(store):
    return Resource.objects.create(
        store=store, type="console", name="Sweep PS5", price_per_hour="50.00"
    )


@pytest.fixture()
def customer(store):
    return Customer.objects.create(store=store, phone="+15559876543", name="Sweeper Customer")


def _make_booking(
    resource,
    customer,
    *,
    minutes_after_end: int,
    status_: str = BookingStatus.CHECKED_IN,
    duration_minutes: int = 60,
    token: str = "SWEEP234",
):
    """Build a booking whose ``end_time`` was N minutes ago."""
    end = timezone.now() - timedelta(minutes=minutes_after_end)
    start = end - timedelta(minutes=duration_minutes)
    return Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        start_time=start,
        end_time=end,
        status=status_,
        check_in_token=token,
    )


def test_promotes_checked_in_with_end_time_60_min_ago(resource, customer):
    booking = _make_booking(resource, customer, minutes_after_end=60)
    out = StringIO()
    call_command("auto_complete_checked_in", stdout=out)
    booking.refresh_from_db()
    assert booking.status == BookingStatus.COMPLETED
    # `booking_thank_you` should now be queued (mock outbound — we just
    # check the OutboundMessage row exists with the right template).
    assert OutboundMessage.objects.filter(
        customer=customer, template_key="booking_thank_you"
    ).exists()
    assert "Promoted 1" in out.getvalue()


def test_skips_when_under_grace_period(resource, customer):
    booking = _make_booking(resource, customer, minutes_after_end=10)
    call_command("auto_complete_checked_in", stdout=StringIO())
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CHECKED_IN


def test_skips_confirmed_not_yet_checked_in(resource, customer):
    booking = _make_booking(
        resource, customer, minutes_after_end=120, status_=BookingStatus.CONFIRMED
    )
    call_command("auto_complete_checked_in", stdout=StringIO())
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED


def test_dry_run_does_not_write(resource, customer):
    booking = _make_booking(resource, customer, minutes_after_end=60)
    out = StringIO()
    call_command("auto_complete_checked_in", "--dry-run", stdout=out)
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CHECKED_IN
    assert not OutboundMessage.objects.filter(template_key="booking_thank_you").exists()
    assert "dry-run" in out.getvalue()


def test_re_running_after_promotion_is_a_noop(resource, customer):
    _make_booking(resource, customer, minutes_after_end=60)
    call_command("auto_complete_checked_in", stdout=StringIO())
    # Capture the count of thank-you messages after the first run.
    first_count = OutboundMessage.objects.filter(template_key="booking_thank_you").count()
    # Second run should not enqueue another.
    out = StringIO()
    call_command("auto_complete_checked_in", stdout=out)
    second_count = OutboundMessage.objects.filter(template_key="booking_thank_you").count()
    assert second_count == first_count
    assert "Promoted 0" in out.getvalue()


def test_store_filter_scopes_to_one_store(store, other_store):
    res_a = Resource.objects.create(
        store=store, type="console", name="A-PS5", price_per_hour="50.00"
    )
    res_b = Resource.objects.create(
        store=other_store, type="console", name="B-PS5", price_per_hour="50.00"
    )
    cust_a = Customer.objects.create(store=store, phone="+15550000111", name="A")
    cust_b = Customer.objects.create(store=other_store, phone="+15550000222", name="B")
    b_a = _make_booking(res_a, cust_a, minutes_after_end=60, token="STOREA12")
    b_b = _make_booking(res_b, cust_b, minutes_after_end=60, token="STOREB12")
    call_command("auto_complete_checked_in", f"--store={store.slug}", stdout=StringIO())
    b_a.refresh_from_db()
    b_b.refresh_from_db()
    assert b_a.status == BookingStatus.COMPLETED
    assert b_b.status == BookingStatus.CHECKED_IN


def test_grace_minutes_override(resource, customer):
    booking = _make_booking(resource, customer, minutes_after_end=15)
    # Default grace is 30 — skip.
    call_command("auto_complete_checked_in", stdout=StringIO())
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CHECKED_IN
    # Lower the grace to 10 — now promote.
    call_command("auto_complete_checked_in", "--grace-minutes=10", stdout=StringIO())
    booking.refresh_from_db()
    assert booking.status == BookingStatus.COMPLETED
