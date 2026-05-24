"""Public /api/c-in/ endpoint tests (v11a, task #205)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from checkin.services import mint_key
from checkin.views import _verified_cache_key
from core.models import (
    Booking,
    BookingStatus,
    Customer,
    CustomerOTP,
    Resource,
    Store,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.urls("tests.urls"),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture()
def anon_client():
    """Bypass conftest's pre-authenticated client — public endpoints are anon."""
    return APIClient()


@pytest.fixture()
def store(db):
    return Store.objects.create(
        name="Door Store", slug="door-store", timezone="UTC", business_hours={}
    )


@pytest.fixture()
def other_store(db):
    return Store.objects.create(
        name="Other Door", slug="other-door", timezone="UTC", business_hours={}
    )


@pytest.fixture()
def resource(store):
    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Door 1",
        capacity=4,
        price_per_hour="60.00",
    )


@pytest.fixture()
def other_resource(other_store):
    return Resource.objects.create(
        store=other_store,
        type="console",
        name="Other PS5",
        capacity=4,
        price_per_hour="60.00",
    )


@pytest.fixture()
def customer(store):
    return Customer.objects.create(store=store, phone="+15551112222", name="Alice")


@pytest.fixture()
def key(store):
    return mint_key(store)


@pytest.fixture()
def mock_sms(monkeypatch):
    sent: list[tuple[str, str]] = []

    class _Adapter:
        def send(self, to, body, metadata=None):
            sent.append((to, body))

            class _R:
                ok = True
                provider_message_id = "stub"
                reason = None

            return _R()

    monkeypatch.setattr("agent.channels.registry.get_outbound_adapter", lambda ch: _Adapter())
    return sent


def _make_booking(
    resource, customer, *, hours_from_now: float = 0.5, status_=BookingStatus.CONFIRMED
):
    start = timezone.now() + timedelta(hours=hours_from_now)
    return Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        start_time=start,
        end_time=start + timedelta(hours=1),
        status=status_,
    )


# ---------------------------------------------------------------------------
# lookup-key
# ---------------------------------------------------------------------------


def test_lookup_key_happy(anon_client, store, key):
    resp = anon_client.post("/api/c-in/lookup-key/", {"key": key.key}, format="json")
    assert resp.status_code == 200
    body = resp.json()
    assert body["store_slug"] == store.slug
    assert body["store_name"] == store.name
    assert "expires_at" in body


def test_lookup_key_unknown_returns_410(anon_client):
    resp = anon_client.post("/api/c-in/lookup-key/", {"key": "NOPENOPE99"}, format="json")
    assert resp.status_code == 410
    assert "ask staff" in resp.json()["detail"].lower()


def test_lookup_key_expired_returns_410(anon_client, key):
    key.expires_at = timezone.now() - timedelta(seconds=1)
    key.save(update_fields=["expires_at"])
    resp = anon_client.post("/api/c-in/lookup-key/", {"key": key.key}, format="json")
    assert resp.status_code == 410


# ---------------------------------------------------------------------------
# request-otp
# ---------------------------------------------------------------------------


def test_request_otp_happy(anon_client, key, customer, mock_sms):
    resp = anon_client.post(
        "/api/c-in/request-otp/",
        {"key": key.key, "phone": customer.phone},
        format="json",
    )
    assert resp.status_code == 201
    assert "request_id" in resp.json()
    assert CustomerOTP.objects.filter(phone=customer.phone).count() == 1
    assert len(mock_sms) == 1


def test_request_otp_invalid_key_410(anon_client, customer, mock_sms):
    resp = anon_client.post(
        "/api/c-in/request-otp/",
        {"key": "NOPE", "phone": customer.phone},
        format="json",
    )
    assert resp.status_code == 410
    assert CustomerOTP.objects.count() == 0


def test_request_otp_rate_limited(anon_client, key, customer, mock_sms):
    body = {"key": key.key, "phone": customer.phone}
    r1 = anon_client.post("/api/c-in/request-otp/", body, format="json")
    assert r1.status_code == 201
    r2 = anon_client.post("/api/c-in/request-otp/", body, format="json")
    assert r2.status_code == 429


# ---------------------------------------------------------------------------
# verify-and-find
# ---------------------------------------------------------------------------


def _seed_valid_otp(phone: str, store: Store, code: str = "123456") -> CustomerOTP:
    return CustomerOTP.objects.create(
        phone=phone,
        store=store,
        code=code,
        expires_at=timezone.now() + timedelta(minutes=10),
    )


def test_verify_and_find_returns_single_match(anon_client, key, customer, resource):
    booking = _make_booking(resource, customer)
    _seed_valid_otp(customer.phone, key.store)
    resp = anon_client.post(
        "/api/c-in/verify-and-find/",
        {"key": key.key, "phone": customer.phone, "code": "123456"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert len(body["bookings"]) == 1
    assert body["bookings"][0]["id"] == booking.id
    assert body["bookings"][0]["can_check_in"] is True
    # Cache flag set; OTP NOT consumed.
    assert cache.get(_verified_cache_key(customer.phone)) is True
    otp = CustomerOTP.objects.get(phone=customer.phone)
    assert otp.used_at is None


def test_verify_and_find_empty_for_walk_in(anon_client, key, customer):
    _seed_valid_otp(customer.phone, key.store)
    resp = anon_client.post(
        "/api/c-in/verify-and-find/",
        {"key": key.key, "phone": customer.phone, "code": "123456"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["bookings"] == []


def test_verify_and_find_invalid_code_401(anon_client, key, customer):
    _seed_valid_otp(customer.phone, key.store, code="111111")
    resp = anon_client.post(
        "/api/c-in/verify-and-find/",
        {"key": key.key, "phone": customer.phone, "code": "999999"},
        format="json",
    )
    assert resp.status_code == 401
    assert cache.get(_verified_cache_key(customer.phone)) is None


def test_verify_and_find_returns_multiple_in_order(anon_client, key, customer, resource, store):
    # Two bookings on DIFFERENT resources (overlap constraint is per-resource);
    # one in 90 min, one in 30 min — confirm order.
    second = Resource.objects.create(
        store=store, type="console", name="PS5 Door 2", capacity=4, price_per_hour="60.00"
    )
    b1 = _make_booking(resource, customer, hours_from_now=1.5)
    b2 = _make_booking(second, customer, hours_from_now=0.5)
    _seed_valid_otp(customer.phone, key.store)
    resp = anon_client.post(
        "/api/c-in/verify-and-find/",
        {"key": key.key, "phone": customer.phone, "code": "123456"},
        format="json",
    )
    assert resp.status_code == 200
    ids = [b["id"] for b in resp.json()["bookings"]]
    assert ids == [b2.id, b1.id]


def test_verify_and_find_skips_cross_store(anon_client, key, customer, other_resource):
    # Booking exists at OTHER store on same phone — lookup must NOT find it.
    other_customer = Customer.objects.create(
        store=other_resource.store, phone=customer.phone, name="Alice Other"
    )
    _make_booking(other_resource, other_customer)
    _seed_valid_otp(customer.phone, key.store)
    resp = anon_client.post(
        "/api/c-in/verify-and-find/",
        {"key": key.key, "phone": customer.phone, "code": "123456"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["bookings"] == []


# ---------------------------------------------------------------------------
# check-in
# ---------------------------------------------------------------------------


def test_check_in_happy_flips_status(anon_client, key, customer, resource):
    booking = _make_booking(resource, customer)
    cache.set(_verified_cache_key(customer.phone), True, timeout=300)
    # Seed an OTP so the single-use consume can find one.
    _seed_valid_otp(customer.phone, key.store)

    resp = anon_client.post(
        "/api/c-in/check-in/",
        {"key": key.key, "phone": customer.phone, "booking_id": booking.id},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["status"] == "checked_in"
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CHECKED_IN
    assert booking.checked_in_at is not None
    # Cache cleared after single-use consume.
    assert cache.get(_verified_cache_key(customer.phone)) is None
    # OTP consumed too.
    assert CustomerOTP.objects.get(phone=customer.phone).used_at is not None


def test_check_in_without_verification_401(anon_client, key, customer, resource):
    booking = _make_booking(resource, customer)
    resp = anon_client.post(
        "/api/c-in/check-in/",
        {"key": key.key, "phone": customer.phone, "booking_id": booking.id},
        format="json",
    )
    assert resp.status_code == 401


def test_check_in_idempotent_on_already_checked_in(anon_client, key, customer, resource):
    booking = _make_booking(resource, customer, status_=BookingStatus.CHECKED_IN)
    booking.checked_in_at = timezone.now()
    booking.save(update_fields=["checked_in_at"])
    cache.set(_verified_cache_key(customer.phone), True, timeout=300)
    resp = anon_client.post(
        "/api/c-in/check-in/",
        {"key": key.key, "phone": customer.phone, "booking_id": booking.id},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "checked_in"


def test_check_in_booking_outside_window_404(anon_client, key, customer, resource):
    booking = _make_booking(resource, customer, hours_from_now=24)
    cache.set(_verified_cache_key(customer.phone), True, timeout=300)
    resp = anon_client.post(
        "/api/c-in/check-in/",
        {"key": key.key, "phone": customer.phone, "booking_id": booking.id},
        format="json",
    )
    assert resp.status_code == 404


def test_check_in_expired_key_410(anon_client, key, customer, resource):
    key.expires_at = timezone.now() - timedelta(seconds=1)
    key.save(update_fields=["expires_at"])
    booking = _make_booking(resource, customer)
    cache.set(_verified_cache_key(customer.phone), True, timeout=300)
    resp = anon_client.post(
        "/api/c-in/check-in/",
        {"key": key.key, "phone": customer.phone, "booking_id": booking.id},
        format="json",
    )
    assert resp.status_code == 410
