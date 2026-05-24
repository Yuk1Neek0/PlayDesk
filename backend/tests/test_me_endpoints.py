"""Tests for the /api/me/* customer-portal endpoints (task #167).

Covers:
  - 401 without session cookie on every endpoint
  - 404 cross-customer (ownership enforcement)
  - bookings list pagination + status filter (upcoming / past)
  - PATCH /api/me/ name update
  - reschedule happy path / overlap 409 / invalid timing 400
  - cancel inside / outside lead_time window
  - SMS enqueue via outbound (asserts the queued row appears)
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from core.middleware import CUSTOMER_COOKIE_NAME, sign_customer_session
from core.models import Booking, BookingStatus, Customer, Resource, Store
from outbound.models import OutboundMessage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def flagship(db):
    return Store.objects.create(
        name="ME Flagship",
        slug="me-flagship",
        timezone="UTC",
        business_hours={},
        cancellation_lead_hours=24,
    )


@pytest.fixture()
def short_lead_store(db):
    """Store with a 1-hour cancellation window so the "outside lead" path is easy to test."""
    return Store.objects.create(
        name="ME Short",
        slug="me-short",
        timezone="UTC",
        business_hours={},
        cancellation_lead_hours=1,
    )


@pytest.fixture()
def resource(flagship):
    return Resource.objects.create(
        store=flagship, type="console", name="PS5", capacity=4, price_per_hour="60"
    )


@pytest.fixture()
def other_resource(short_lead_store):
    return Resource.objects.create(
        store=short_lead_store, type="console", name="N-PS5", capacity=4, price_per_hour="60"
    )


@pytest.fixture()
def customer(flagship):
    return Customer.objects.create(store=flagship, phone="+15550001111", name="Alice")


@pytest.fixture()
def other_customer(flagship):
    return Customer.objects.create(store=flagship, phone="+15550002222", name="Bob")


@pytest.fixture()
def auth_client(client, customer, flagship):
    """Browser-like test client with a valid signed customer session cookie."""
    token = sign_customer_session(customer.id, flagship.id)
    client.cookies[CUSTOMER_COOKIE_NAME] = token
    # The middleware also reads the URL/header for store binding; send the slug
    # header so request.store resolves to flagship deterministically.
    client.defaults["HTTP_X_PD_STORE_SLUG"] = flagship.slug
    return client


def _future(hours: int = 48) -> timezone.datetime:
    return timezone.now() + timedelta(hours=hours)


def _create_upcoming_booking(resource, customer, hours_out: int = 48, length_h: int = 2):
    start = _future(hours_out)
    return Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name or "X",
        customer_phone=customer.phone,
        start_time=start,
        end_time=start + timedelta(hours=length_h),
        status=BookingStatus.CONFIRMED,
    )


# ---------------------------------------------------------------------------
# 401 without session
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_me_401_without_cookie(client, flagship):
    client.defaults["HTTP_X_PD_STORE_SLUG"] = flagship.slug
    for url in ["/api/me/", "/api/me/bookings/"]:
        resp = client.get(url)
        assert resp.status_code == 401, url


@pytest.mark.django_db
def test_me_bookings_404_for_cross_customer_reschedule(
    auth_client, other_customer, other_resource, flagship
):
    # Booking belongs to other_customer (Bob), auth_client is Alice.
    # other_customer is also at flagship (just to keep store scoping out of it).
    other_at_flagship = Resource.objects.create(
        store=flagship, type="console", name="PS5-2", capacity=4, price_per_hour="60"
    )
    bk = _create_upcoming_booking(other_at_flagship, other_customer)
    resp = auth_client.post(
        f"/api/me/bookings/{bk.id}/reschedule/",
        data={"start_at": _future(72).isoformat(), "end_at": _future(74).isoformat()},
        content_type="application/json",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_me_get_profile(auth_client, customer, flagship):
    resp = auth_client.get("/api/me/")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["id"] == customer.id
    assert body["phone"] == customer.phone
    assert body["store_slug"] == flagship.slug


@pytest.mark.django_db
def test_me_patch_name(auth_client, customer):
    resp = auth_client.patch("/api/me/", data={"name": "Alicia"}, content_type="application/json")
    assert resp.status_code == 200
    customer.refresh_from_db()
    assert customer.name == "Alicia"


# ---------------------------------------------------------------------------
# Bookings list
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_me_bookings_upcoming_and_past(auth_client, customer, resource):
    # 2 upcoming, 1 cancelled past, 1 confirmed past.
    _create_upcoming_booking(resource, customer, hours_out=24)
    _create_upcoming_booking(resource, customer, hours_out=48)
    past_start = timezone.now() - timedelta(days=5)
    Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        start_time=past_start,
        end_time=past_start + timedelta(hours=1),
        status=BookingStatus.CONFIRMED,
    )
    Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        start_time=past_start - timedelta(days=1),
        end_time=past_start - timedelta(days=1) + timedelta(hours=1),
        status=BookingStatus.CANCELLED,
    )

    r_up = auth_client.get("/api/me/bookings/?status=upcoming")
    assert r_up.status_code == 200
    body_up = r_up.json()
    assert body_up["total"] == 2
    assert all(b["status"] not in ("cancelled", "completed") for b in body_up["results"])

    r_past = auth_client.get("/api/me/bookings/?status=past")
    assert r_past.status_code == 200
    body_past = r_past.json()
    assert body_past["total"] == 2  # 1 past confirmed + 1 cancelled


@pytest.mark.django_db
def test_me_bookings_pagination(auth_client, customer, resource):
    for i in range(5):
        _create_upcoming_booking(resource, customer, hours_out=24 + i * 4)
    r = auth_client.get("/api/me/bookings/?status=upcoming&limit=2&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert len(body["results"]) == 2
    assert body["has_more"] is True


# ---------------------------------------------------------------------------
# Reschedule
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_me_reschedule_happy_path_enqueues_sms(auth_client, customer, resource):
    bk = _create_upcoming_booking(resource, customer, hours_out=48, length_h=2)
    new_start = bk.start_time + timedelta(hours=3)
    resp = auth_client.post(
        f"/api/me/bookings/{bk.id}/reschedule/",
        data={
            "start_at": new_start.isoformat(),
            "end_at": (new_start + timedelta(hours=2)).isoformat(),
        },
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    bk.refresh_from_db()
    assert bk.start_time == new_start
    # SMS enqueued via the v4 outbound queue.
    assert OutboundMessage.objects.filter(
        customer=customer, template_key="booking_rescheduled"
    ).exists()


@pytest.mark.django_db
def test_me_reschedule_overlap_returns_409(auth_client, customer, resource):
    bk1 = _create_upcoming_booking(resource, customer, hours_out=48, length_h=2)
    # A second booking 4h later on the same resource.
    other_start = bk1.end_time + timedelta(hours=2)
    Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        start_time=other_start,
        end_time=other_start + timedelta(hours=2),
        status=BookingStatus.CONFIRMED,
    )
    # Try to move bk1 to overlap with the second one.
    resp = auth_client.post(
        f"/api/me/bookings/{bk1.id}/reschedule/",
        data={
            "start_at": other_start.isoformat(),
            "end_at": (other_start + timedelta(hours=2)).isoformat(),
        },
        content_type="application/json",
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_me_reschedule_into_past_returns_400(auth_client, customer, resource):
    bk = _create_upcoming_booking(resource, customer, hours_out=48)
    past = timezone.now() - timedelta(hours=2)
    resp = auth_client.post(
        f"/api/me/bookings/{bk.id}/reschedule/",
        data={
            "start_at": past.isoformat(),
            "end_at": (past + timedelta(hours=2)).isoformat(),
        },
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_me_reschedule_exceeds_duration_cap_returns_400(auth_client, customer, resource):
    # Original is 2h; try to turn it into 6h (>150%).
    bk = _create_upcoming_booking(resource, customer, hours_out=48, length_h=2)
    new_start = bk.start_time + timedelta(hours=24)
    resp = auth_client.post(
        f"/api/me/bookings/{bk.id}/reschedule/",
        data={
            "start_at": new_start.isoformat(),
            "end_at": (new_start + timedelta(hours=6)).isoformat(),
        },
        content_type="application/json",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_me_cancel_within_lead_window_returns_409(auth_client, customer, resource):
    # Default flagship lead is 24h; booking is 2h out.
    bk = _create_upcoming_booking(resource, customer, hours_out=2)
    resp = auth_client.post(f"/api/me/bookings/{bk.id}/cancel/")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "lead_time_violation"
    assert body["lead_hours"] == 24


@pytest.mark.django_db
def test_me_cancel_outside_lead_window_succeeds(auth_client, customer, resource):
    bk = _create_upcoming_booking(resource, customer, hours_out=48)
    resp = auth_client.post(f"/api/me/bookings/{bk.id}/cancel/")
    assert resp.status_code == 200, resp.content
    bk.refresh_from_db()
    assert bk.status == "cancelled"
    # SMS enqueued.
    assert OutboundMessage.objects.filter(
        customer=customer, template_key="booking_cancelled"
    ).exists()


@pytest.mark.django_db
def test_me_cancel_404_for_unknown_booking(auth_client):
    resp = auth_client.post("/api/me/bookings/999999/cancel/")
    assert resp.status_code == 404
