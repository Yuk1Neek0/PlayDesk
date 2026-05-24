"""Tests for the customer-portal auth foundation (task #166).

Covers:
  - request-code: OTP row created, SMS dispatched, rate limits enforced.
  - verify-code: happy path sets cookie + returns customer; bad code,
    expired code, attempt cap, wrong store, unknown phone all 401/429.
  - logout: clears the cookie.
  - CustomerSessionMiddleware: valid cookie → request.customer set;
    stale store / tampered signature → request.customer is None +
    cookie cleared.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from django.urls import ResolverMatch
from django.utils import timezone

from core.middleware import (
    CUSTOMER_COOKIE_NAME,
    CurrentStoreMiddleware,
    CustomerSessionMiddleware,
    sign_customer_session,
)
from core.models import Customer, CustomerLoginAttempt, CustomerOTP, Store

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache():
    """Per-test cache flush so rate-limit keys don't leak between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture()
def flagship(db):
    return Store.objects.create(
        name="Flagship CP", slug="cp-flagship", timezone="UTC", business_hours={}
    )


@pytest.fixture()
def north(db):
    return Store.objects.create(name="North CP", slug="cp-north", timezone="UTC", business_hours={})


@pytest.fixture()
def customer_at_flagship(flagship):
    return Customer.objects.create(store=flagship, phone="+15551234567", name="Alice")


@pytest.fixture()
def mock_sms(monkeypatch):
    """Replace the SMS outbound adapter with a recording mock."""
    sent: list[tuple[str, str]] = []

    class _StubAdapter:
        def send(self, to, body, metadata=None):
            sent.append((to, body))

            class _R:
                ok = True
                provider_message_id = "stub-sid"
                reason = None

            return _R()

    def _get(channel):
        assert channel == "sms"
        return _StubAdapter()

    monkeypatch.setattr("agent.channels.registry.get_outbound_adapter", _get)
    return sent


# ---------------------------------------------------------------------------
# request-code
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_request_code_creates_otp_and_sends_sms(client, flagship, mock_sms):
    resp = client.post(
        "/api/customer-auth/request-code/",
        data={"phone": "+15551234567", "store_slug": flagship.slug},
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert "request_id" in body

    otp = CustomerOTP.objects.get(pk=body["request_id"])
    assert otp.phone == "+15551234567"
    assert otp.store_id == flagship.id
    assert otp.used_at is None
    assert len(otp.code) == 6 and otp.code.isdigit()
    assert otp.expires_at > timezone.now()

    # SMS adapter was called once.
    assert len(mock_sms) == 1
    to, body = mock_sms[0]
    assert to == "+15551234567"
    assert otp.code in body


@pytest.mark.django_db
def test_request_code_per_minute_rate_limit(client, flagship, mock_sms):
    body = {"phone": "+15551234567", "store_slug": flagship.slug}
    r1 = client.post("/api/customer-auth/request-code/", data=body, content_type="application/json")
    assert r1.status_code == 201
    r2 = client.post("/api/customer-auth/request-code/", data=body, content_type="application/json")
    assert r2.status_code == 429


@pytest.mark.django_db
def test_request_code_hour_rate_limit(client, flagship, mock_sms):
    # Pre-seed the hourly counter at the cap.
    cache.set(f"otp:req:{flagship.id}:+15551234567:1h", 5, timeout=3600)
    resp = client.post(
        "/api/customer-auth/request-code/",
        data={"phone": "+15551234567", "store_slug": flagship.slug},
        content_type="application/json",
    )
    assert resp.status_code == 429


@pytest.mark.django_db
def test_request_code_invalidates_prior_otp(client, flagship, mock_sms):
    body = {"phone": "+15551234567", "store_slug": flagship.slug}
    r1 = client.post("/api/customer-auth/request-code/", data=body, content_type="application/json")
    assert r1.status_code == 201
    prior_id = r1.json()["request_id"]

    # Bypass the per-minute lockout to issue a second one.
    cache.delete(f"otp:req:{flagship.id}:+15551234567:1m")
    r2 = client.post("/api/customer-auth/request-code/", data=body, content_type="application/json")
    assert r2.status_code == 201

    prior = CustomerOTP.objects.get(pk=prior_id)
    assert prior.used_at is not None


@pytest.mark.django_db
def test_request_code_unknown_store_404(client, mock_sms):
    resp = client.post(
        "/api/customer-auth/request-code/",
        data={"phone": "+15551234567", "store_slug": "no-such-store"},
        content_type="application/json",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# verify-code
# ---------------------------------------------------------------------------


def _create_valid_otp(phone: str, store: Store, code: str = "123456") -> CustomerOTP:
    return CustomerOTP.objects.create(
        phone=phone,
        store=store,
        code=code,
        expires_at=timezone.now() + timedelta(minutes=10),
    )


@pytest.mark.django_db
def test_verify_code_happy_path_sets_cookie_and_returns_customer(
    client, flagship, customer_at_flagship
):
    otp = _create_valid_otp(customer_at_flagship.phone, flagship, code="654321")
    resp = client.post(
        "/api/customer-auth/verify-code/",
        data={
            "phone": customer_at_flagship.phone,
            "code": "654321",
            "store_slug": flagship.slug,
        },
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["customer"]["id"] == customer_at_flagship.id
    assert body["customer"]["name"] == "Alice"
    assert CUSTOMER_COOKIE_NAME in resp.cookies
    # OTP marked used.
    otp.refresh_from_db()
    assert otp.used_at is not None
    # Login attempt logged.
    assert CustomerLoginAttempt.objects.filter(
        phone=customer_at_flagship.phone, success=True
    ).exists()


@pytest.mark.django_db
def test_verify_code_wrong_code_increments_attempts_until_invalidated(
    client, flagship, customer_at_flagship
):
    otp = _create_valid_otp(customer_at_flagship.phone, flagship, code="000000")
    for _ in range(5):
        r = client.post(
            "/api/customer-auth/verify-code/",
            data={
                "phone": customer_at_flagship.phone,
                "code": "999999",
                "store_slug": flagship.slug,
            },
            content_type="application/json",
        )
        assert r.status_code == 401, r.content
    # 6th attempt → 429 + OTP invalidated.
    r6 = client.post(
        "/api/customer-auth/verify-code/",
        data={
            "phone": customer_at_flagship.phone,
            "code": "999999",
            "store_slug": flagship.slug,
        },
        content_type="application/json",
    )
    assert r6.status_code == 429
    otp.refresh_from_db()
    assert otp.attempts > 5
    assert otp.used_at is not None


@pytest.mark.django_db
def test_verify_code_expired_returns_401(client, flagship, customer_at_flagship):
    CustomerOTP.objects.create(
        phone=customer_at_flagship.phone,
        store=flagship,
        code="123456",
        expires_at=timezone.now() - timedelta(minutes=1),
    )
    resp = client.post(
        "/api/customer-auth/verify-code/",
        data={
            "phone": customer_at_flagship.phone,
            "code": "123456",
            "store_slug": flagship.slug,
        },
        content_type="application/json",
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_verify_code_unknown_phone_records_failed_attempt(client, flagship):
    _create_valid_otp("+15559998888", flagship, code="123456")
    resp = client.post(
        "/api/customer-auth/verify-code/",
        data={
            "phone": "+15559998888",
            "code": "123456",
            "store_slug": flagship.slug,
        },
        content_type="application/json",
    )
    assert resp.status_code == 401
    assert CUSTOMER_COOKIE_NAME not in resp.cookies
    assert CustomerLoginAttempt.objects.filter(phone="+15559998888", success=False).exists()


@pytest.mark.django_db
def test_verify_code_cross_store_rejects(client, flagship, north, customer_at_flagship):
    # Customer exists at flagship but the OTP is issued (and verified) against North.
    _create_valid_otp(customer_at_flagship.phone, north, code="123456")
    resp = client.post(
        "/api/customer-auth/verify-code/",
        data={
            "phone": customer_at_flagship.phone,
            "code": "123456",
            "store_slug": north.slug,
        },
        content_type="application/json",
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_logout_clears_cookie(client):
    resp = client.post("/api/customer-auth/logout/")
    assert resp.status_code == 200
    cookie = resp.cookies.get(CUSTOMER_COOKIE_NAME)
    assert cookie is not None
    # Cleared cookies have an empty value + Max-Age=0 / expires in the past.
    assert cookie.value == ""


# ---------------------------------------------------------------------------
# CustomerSessionMiddleware
# ---------------------------------------------------------------------------


def _request_with_store_and_cookie(
    store: Store, cookie_value: str | None
) -> tuple[HttpRequest, HttpResponse]:
    """Drive a request through CurrentStoreMiddleware + CustomerSessionMiddleware."""
    rf = RequestFactory()
    request = rf.get("/some-path")
    if cookie_value is not None:
        request.COOKIES[CUSTOMER_COOKIE_NAME] = cookie_value
    request.resolver_match = ResolverMatch(
        func=lambda *_a, **_k: None,
        args=(),
        kwargs={"store_slug": store.slug},
        url_name="test",
    )
    response_holder: dict[str, HttpResponse] = {}

    def _inner(req):
        # Capture the request mid-flight so the test can assert on it.
        response_holder["req"] = req
        return HttpResponse(status=200)

    # Wrap in both middlewares (order matches settings.py).
    stack = CustomerSessionMiddleware(CurrentStoreMiddleware(_inner))
    response = stack(request)
    return response_holder["req"], response


@pytest.mark.django_db
def test_middleware_sets_customer_for_valid_cookie(flagship, customer_at_flagship):
    token = sign_customer_session(customer_at_flagship.id, flagship.id)
    req, _ = _request_with_store_and_cookie(flagship, token)
    assert req.customer is not None
    assert req.customer.id == customer_at_flagship.id


@pytest.mark.django_db
def test_middleware_rejects_cookie_with_stale_store(flagship, north, customer_at_flagship):
    # Cookie binds to flagship; request resolves to north.
    token = sign_customer_session(customer_at_flagship.id, flagship.id)
    req, resp = _request_with_store_and_cookie(north, token)
    assert req.customer is None
    # Cookie cleared in response.
    assert CUSTOMER_COOKIE_NAME in resp.cookies
    assert resp.cookies[CUSTOMER_COOKIE_NAME].value == ""


@pytest.mark.django_db
def test_middleware_rejects_tampered_signature(flagship):
    req, resp = _request_with_store_and_cookie(flagship, "not-a-valid-signed-cookie")
    assert req.customer is None
    assert CUSTOMER_COOKIE_NAME in resp.cookies


@pytest.mark.django_db
def test_middleware_unset_when_no_cookie(flagship):
    req, _ = _request_with_store_and_cookie(flagship, cookie_value=None)
    assert req.customer is None
