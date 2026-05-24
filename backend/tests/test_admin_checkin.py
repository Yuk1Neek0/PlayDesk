"""Tests for the admin manual check-in / undo endpoints + audit notes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from core.models import Booking, BookingStatus, Customer, CustomerNote, Resource, Store

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.urls("tests.urls"),
]


# Local `client` / `APIClient()` fixtures removed post-v10a: the root
# conftest's `client` fixture is now pre-staff-logged-in via
# `force_login(test_staff)`, which is exactly what these admin endpoint
# tests need to clear `StaffOnlyMiddleware`. Tests that want a specific
# staff user override the session with `client.force_login(my_user)`.
# Tests that want an unauthenticated baseline use `anon_client`.


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Admin Check-in Store", timezone="UTC", business_hours={})


@pytest.fixture()
def other_store(db):
    return Store.objects.create(name="Other Store", timezone="UTC", business_hours={})


@pytest.fixture()
def resource(store):
    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Admin Station",
        capacity=4,
        price_per_hour="50.00",
    )


@pytest.fixture()
def customer(store):
    return Customer.objects.create(store=store, phone="+15551234567", name="Audit Tester")


def _make_booking(resource, customer, status_=BookingStatus.CONFIRMED, token="ADMNTEST"):
    start = timezone.now() + timedelta(hours=1)
    return Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        start_time=start,
        end_time=start + timedelta(hours=1),
        status=status_,
        check_in_token=token,
    )


def test_manual_check_in_confirmed_flips_and_writes_note(client, resource, customer):
    booking = _make_booking(resource, customer)
    resp = client.post(reverse("api:admin-booking-checkin", args=[booking.pk]))
    assert resp.status_code == 200, resp.content
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CHECKED_IN
    assert booking.checked_in_at is not None
    notes = list(CustomerNote.objects.filter(customer=customer))
    assert len(notes) == 1
    assert "Manually checked in" in notes[0].body


def test_manual_check_in_when_already_checked_in_returns_400(client, resource, customer):
    booking = _make_booking(resource, customer, status_=BookingStatus.CHECKED_IN)
    resp = client.post(reverse("api:admin-booking-checkin", args=[booking.pk]))
    assert resp.status_code == 400


def test_undo_check_in_reverts_status(client, resource, customer):
    booking = _make_booking(resource, customer, status_=BookingStatus.CHECKED_IN)
    booking.checked_in_at = timezone.now()
    booking.save()
    resp = client.post(reverse("api:admin-booking-undo-checkin", args=[booking.pk]))
    assert resp.status_code == 200
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED
    assert booking.checked_in_at is None
    notes = list(CustomerNote.objects.filter(customer=customer))
    assert any("undone" in n.body.lower() for n in notes)


def test_undo_non_checked_in_returns_400(client, resource, customer):
    booking = _make_booking(resource, customer)
    resp = client.post(reverse("api:admin-booking-undo-checkin", args=[booking.pk]))
    assert resp.status_code == 400


def test_cross_store_access_returns_404(client, store, other_store):
    other_resource = Resource.objects.create(
        store=other_store,
        type="console",
        name="OtherStation",
        capacity=2,
        price_per_hour="40.00",
    )
    other_customer = Customer.objects.create(
        store=other_store, phone="+15559990000", name="Foreigner"
    )
    booking = _make_booking(other_resource, other_customer, token="OTHRTEST")
    # Make our request scope to `store` — the other booking should be 404.
    resp = client.post(
        reverse("api:admin-booking-checkin", args=[booking.pk]),
        HTTP_X_PD_STORE_SLUG=store.slug,
    )
    assert resp.status_code == 404


def test_authenticated_staff_attribution_on_note(client, resource, customer):
    """A specific staff user logged in via `force_login` should be
    attributed on the CustomerNote (replaces the default test_staff
    session for the duration of this test)."""
    User = get_user_model()
    user = User.objects.create_user(username="staffer", password="x", is_staff=True)
    client.force_login(user)
    booking = _make_booking(resource, customer, token="AUTH2345")
    resp = client.post(reverse("api:admin-booking-checkin", args=[booking.pk]))
    assert resp.status_code == 200
    note = CustomerNote.objects.get(customer=customer)
    assert note.author_id == user.pk


def test_anonymous_request_blocked_by_middleware(anon_client, resource, customer):
    """Post-v10a: anonymous requests to /api/admin/* return 401 from
    StaffOnlyMiddleware before the view ever runs. Replaces the prior
    `anonymous_falls_back_to_null_author` test, which encoded the
    pre-v10a behaviour (open admin endpoints + null attribution)."""
    booking = _make_booking(resource, customer, token="ANON2345")
    resp = anon_client.post(reverse("api:admin-booking-checkin", args=[booking.pk]))
    assert resp.status_code == 401
    # And the booking is unchanged.
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED
    assert not CustomerNote.objects.filter(customer=customer).exists()


def test_admin_bookings_list_checked_in_filter(client, resource, customer):
    not_yet = _make_booking(resource, customer, token="NOTYET12")
    # Stagger the second booking's start time to avoid the GIST overlap
    # exclusion constraint firing against the first.
    other_customer = Customer.objects.create(store=resource.store, phone="+15550000999", name="Ned")
    start = timezone.now() + timedelta(hours=3)
    checked = Booking.objects.create(
        resource=resource,
        customer=other_customer,
        customer_name=other_customer.name,
        customer_phone=other_customer.phone,
        start_time=start,
        end_time=start + timedelta(hours=1),
        status=BookingStatus.CHECKED_IN,
        check_in_token="DIDYES12",
    )

    resp_yes = client.get(reverse("api:admin-booking-list"), {"checked_in": "yes"})
    assert resp_yes.status_code == 200
    ids = {b["id"] for b in resp_yes.json()["results"]}
    assert checked.pk in ids and not_yet.pk not in ids

    resp_no = client.get(reverse("api:admin-booking-list"), {"checked_in": "no"})
    ids_no = {b["id"] for b in resp_no.json()["results"]}
    assert not_yet.pk in ids_no and checked.pk not in ids_no
