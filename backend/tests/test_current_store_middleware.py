"""Tests for ``core.middleware.CurrentStoreMiddleware``.

The middleware sets ``request.store`` from header → cookie → URL kwarg →
alphabetically-first fallback. Tests exercise each branch and the
header-driven cookie write side-effect.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from django.urls import ResolverMatch

from core.middleware import COOKIE_NAME, CurrentStoreMiddleware
from core.models import Store


@pytest.fixture()
def stores(db):
    """Two stores; alphabetically: "alpha" < "beta"."""
    a = Store.objects.create(name="Alpha Store", slug="alpha", timezone="UTC", business_hours={})
    b = Store.objects.create(name="Beta Store", slug="beta", timezone="UTC", business_hours={})
    return {"alpha": a, "beta": b}


def _make_middleware():
    """Build a middleware wrapping a no-op view returning HTTP 200."""
    inner = MagicMock(return_value=HttpResponse(status=200))
    mw = CurrentStoreMiddleware(inner)
    return mw, inner


def _attach_resolver_match(request: HttpRequest, kwargs: dict) -> None:
    """Pretend Django's URL dispatcher matched a route with ``kwargs``."""
    request.resolver_match = ResolverMatch(
        func=lambda *_a, **_k: None,
        args=(),
        kwargs=kwargs,
        url_name="test",
    )


# ---------------------------------------------------------------------------
# Resolver chain
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_header_wins(stores):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/api/admin/bookings/", HTTP_X_PD_STORE_SLUG="beta")
    mw(request)
    assert request.store.slug == "beta"


@pytest.mark.django_db
def test_cookie_used_without_header(stores):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/api/admin/bookings/")
    request.COOKIES[COOKIE_NAME] = "alpha"
    mw(request)
    assert request.store.slug == "alpha"


@pytest.mark.django_db
def test_url_kwarg_wins_over_header(stores):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/s/alpha/book", HTTP_X_PD_STORE_SLUG="beta")
    _attach_resolver_match(request, {"store_slug": "alpha"})
    mw(request)
    assert request.store.slug == "alpha"


@pytest.mark.django_db
def test_fallback_to_alphabetically_first(stores):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/api/admin/bookings/")
    mw(request)
    assert request.store.slug == "alpha"


@pytest.mark.django_db
def test_header_beats_cookie(stores):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/api/admin/bookings/", HTTP_X_PD_STORE_SLUG="beta")
    request.COOKIES[COOKIE_NAME] = "alpha"
    mw(request)
    assert request.store.slug == "beta"


@pytest.mark.django_db
def test_invalid_header_falls_through_to_cookie(stores):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/api/admin/bookings/", HTTP_X_PD_STORE_SLUG="nonexistent")
    request.COOKIES[COOKIE_NAME] = "beta"
    mw(request)
    assert request.store.slug == "beta"


@pytest.mark.django_db
def test_invalid_everything_falls_back_to_first(stores):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/api/admin/bookings/", HTTP_X_PD_STORE_SLUG="nope")
    request.COOKIES[COOKIE_NAME] = "also-nope"
    mw(request)
    assert request.store.slug == "alpha"


# ---------------------------------------------------------------------------
# Side-effects + perf
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_header_resolution_sets_cookie_on_response(stores):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/api/admin/bookings/", HTTP_X_PD_STORE_SLUG="beta")
    response = mw(request)
    cookie = response.cookies.get(COOKIE_NAME)
    assert cookie is not None
    assert cookie.value == "beta"
    assert cookie["samesite"].lower() == "lax"


@pytest.mark.django_db
def test_cookie_resolution_does_not_overwrite_cookie(stores):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/api/admin/bookings/")
    request.COOKIES[COOKIE_NAME] = "alpha"
    response = mw(request)
    # No header was set → no need to re-write the cookie.
    assert COOKIE_NAME not in response.cookies


@pytest.mark.django_db
def test_request_store_is_cached(stores, django_assert_num_queries):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/api/admin/bookings/", HTTP_X_PD_STORE_SLUG="beta")
    mw(request)
    # Second + third access should be free (cached on _cached_store).
    with django_assert_num_queries(0):
        _ = request.store
        _ = request.store


@pytest.mark.django_db
def test_no_stores_at_all_yields_none(db):
    mw, _ = _make_middleware()
    rf = RequestFactory()
    request = rf.get("/api/admin/bookings/")
    mw(request)
    assert request.store is None
