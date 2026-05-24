"""Tests for the public `/api/c/<token>/` endpoints (v10b checkin).

Covers:
- GET on each booking state returns the right `can_check_in` + message.
- GET on an unknown token 404s.
- POST flips a CONFIRMED booking to CHECKED_IN.
- POST is idempotent — a second tap on an already-checked-in booking
  returns 200 with the same payload, never 409.
- POST on a CANCELLED booking returns 409.
- Token lookup is uppercase-normalised — lowercase URL still resolves.
- BookingCreateSerializer.create assigns a token at booking creation.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Booking, BookingStatus, Customer, Resource, Store

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.urls("tests.urls"),
]


@pytest.fixture()
def client():
    return APIClient()


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Checkin Store", timezone="UTC", business_hours={})


@pytest.fixture()
def resource(store):
    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Test Station",
        capacity=4,
        price_per_hour="50.00",
    )


@pytest.fixture()
def customer(store):
    return Customer.objects.create(store=store, phone="+15551234567", name="Tora Tester")


def _make_booking(resource, customer, status_=BookingStatus.CONFIRMED, token="ABCD2345"):
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


# ---------------------------------------------------------------------------
# GET /api/c/<token>/
# ---------------------------------------------------------------------------


def test_get_confirmed_returns_can_check_in_true(client, resource, customer):
    booking = _make_booking(resource, customer)
    resp = client.get(reverse("api:checkin-info", args=[booking.check_in_token]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["can_check_in"] is True
    assert body["message"] == "Ready to check in"
    assert body["status"] == "confirmed"
    assert body["store_slug"] == resource.store.slug
    assert body["customer_name"] == "Tora Tester"


def test_get_cancelled_returns_can_check_in_false_with_cancelled_message(
    client, resource, customer
):
    booking = _make_booking(resource, customer, status_=BookingStatus.CANCELLED)
    resp = client.get(reverse("api:checkin-info", args=[booking.check_in_token]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["can_check_in"] is False
    assert body["message"] == "This booking was cancelled"


def test_get_unknown_token_returns_404(client):
    resp = client.get(reverse("api:checkin-info", args=["NOPE9876"]))
    assert resp.status_code == 404


def test_get_lowercase_token_resolves(client, resource, customer):
    booking = _make_booking(resource, customer, token="HELLO234")
    resp = client.get(reverse("api:checkin-info", args=["hello234"]))
    assert resp.status_code == 200
    assert resp.json()["booking_id"] == booking.pk


# ---------------------------------------------------------------------------
# POST /api/c/<token>/check-in/
# ---------------------------------------------------------------------------


def test_post_confirmed_flips_to_checked_in(client, resource, customer):
    booking = _make_booking(resource, customer)
    resp = client.post(reverse("api:checkin-action", args=[booking.check_in_token]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "checked_in"
    assert body["checked_in_at"] is not None
    assert body["can_check_in"] is False
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CHECKED_IN
    assert booking.checked_in_at is not None


def test_post_already_checked_in_is_idempotent(client, resource, customer):
    booking = _make_booking(resource, customer)
    # First tap.
    first = client.post(reverse("api:checkin-action", args=[booking.check_in_token]))
    assert first.status_code == 200
    first_ts = first.json()["checked_in_at"]
    # Second tap — same booking. Must not change timestamp, must not 409.
    second = client.post(reverse("api:checkin-action", args=[booking.check_in_token]))
    assert second.status_code == 200
    assert second.json()["checked_in_at"] == first_ts
    assert second.json()["status"] == "checked_in"


def test_post_cancelled_returns_409(client, resource, customer):
    booking = _make_booking(resource, customer, status_=BookingStatus.CANCELLED)
    resp = client.post(reverse("api:checkin-action", args=[booking.check_in_token]))
    assert resp.status_code == 409
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED


def test_post_unknown_token_returns_404(client):
    resp = client.post(reverse("api:checkin-action", args=["NOTREAL2"]))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# BookingCreateSerializer assigns a check_in_token at create-time
# ---------------------------------------------------------------------------


def test_booking_create_assigns_token(client, resource, store):
    start = (timezone.now() + timedelta(hours=2)).isoformat()
    end = (timezone.now() + timedelta(hours=3)).isoformat()
    payload = {
        "resource_id": resource.pk,
        "customer_name": "Newbie",
        "customer_phone": "+14165550199",
        "start_time": start,
        "end_time": end,
    }
    resp = client.post(reverse("api:booking-list"), payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    booking = Booking.objects.get(pk=resp.json()["id"])
    assert booking.check_in_token
    assert len(booking.check_in_token) == 8
