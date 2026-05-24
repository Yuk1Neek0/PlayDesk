"""Request-scoped current-store resolver.

Sets ``request.store`` on every request from (first-hit wins):

  1. URL kwarg ``store_slug`` (set by the customer-facing ``/s/[slug]/...``
     URL pattern resolved by Django's URL dispatcher).
  2. ``X-PD-Store-Slug`` request header (admin frontend sets this from its
     ``StoreContext``).
  3. ``pd_store_slug`` cookie (admin selector persists here).
  4. Fallback: the alphabetically-first ``Store`` so legacy single-store
     deployments and bookmarks keep working unchanged.

Side-effects:
  * When the header resolution wins, the same slug is written to the
    ``pd_store_slug`` cookie on the response so cross-tab navigation keeps
    the same store.
  * If a slug doesn't match an existing store, the resolver falls through
    to the next step instead of 404'ing.

The resolved Store is lazily attached as ``request.store`` via a descriptor
so views can read it cheaply (single DB lookup per request — cached on
``request._cached_store``).
"""

from __future__ import annotations

import json
import time as _time
from typing import TYPE_CHECKING

from django.core import signing
from django.http import JsonResponse

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


COOKIE_NAME = "pd_store_slug"
HEADER_NAME = "HTTP_X_PD_STORE_SLUG"
# 1 year — admin sessions are durable and the cookie is just a preference.
_COOKIE_MAX_AGE = 60 * 60 * 24 * 365

# ---------------------------------------------------------------------------
# Customer-portal (v7) — signed session cookie
# ---------------------------------------------------------------------------
CUSTOMER_COOKIE_NAME = "pd_customer_session"
# 30 days. The cookie payload also carries `exp` so a stolen, never-renewed
# cookie can't outlive its TTL even if the rotation skew makes the cookie's
# signed timestamp look fresh.
CUSTOMER_COOKIE_MAX_AGE = 60 * 60 * 24 * 30
# Internal signing salt — separate from anywhere else we use TimestampSigner
# so a value lifted from one context can't be replayed in another.
_CUSTOMER_COOKIE_SALT = "pd.customer.session.v1"


def sign_customer_session(customer_id: int, store_id: int) -> str:
    """Sign `{customer_id, store_id, exp}` for the customer session cookie.

    Returns a single signed string suitable for `Set-Cookie`. The cookie
    is `HttpOnly`, `Secure`, `SameSite=Lax`, 30-day TTL; the binding to
    `store_id` means a stolen cookie can't cross-leak between two stores
    the same phone belongs to.
    """
    payload = {
        "customer_id": int(customer_id),
        "store_id": int(store_id),
        "exp": int(_time.time()) + CUSTOMER_COOKIE_MAX_AGE,
    }
    signer = signing.TimestampSigner(salt=_CUSTOMER_COOKIE_SALT)
    return signer.sign(json.dumps(payload, separators=(",", ":")))


def unsign_customer_session(token: str) -> dict | None:
    """Validate + return the cookie payload, or None on any failure.

    Failures: bad signature, expired (cookie age > max-age via signer's
    own check), missing/invalid JSON, exp in the past.
    """
    signer = signing.TimestampSigner(salt=_CUSTOMER_COOKIE_SALT)
    try:
        raw = signer.unsign(token, max_age=CUSTOMER_COOKIE_MAX_AGE)
    except signing.BadSignature:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("customer_id"), int):
        return None
    if not isinstance(payload.get("store_id"), int):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(_time.time()):
        return None
    return payload


def _lookup_store_by_slug(slug: str | None):
    """Return the Store with ``slug`` or ``None``. One DB query, no exception."""
    from .models import Store

    if not slug:
        return None
    return Store.objects.filter(slug=slug).first()


def _fallback_store():
    """Return the alphabetically-first store, or ``None`` if there are none."""
    from .models import Store

    return Store.objects.order_by("slug").first()


def _resolve_store(request: HttpRequest):
    """Run the resolver chain. Returns ``(store, source)``.

    ``source`` is one of ``"url"``, ``"header"``, ``"cookie"``, ``"fallback"``
    so the middleware can decide whether to write the cookie on the response.
    Returns ``(None, "fallback")`` when no store exists at all.
    """
    # 1. URL kwarg — set by the customer-facing /s/<slug>/... routes.
    url_slug: str | None = None
    resolver_match = getattr(request, "resolver_match", None)
    if resolver_match is not None:
        url_slug = (resolver_match.kwargs or {}).get("store_slug")
    store = _lookup_store_by_slug(url_slug)
    if store is not None:
        return store, "url"

    # 2. Header.
    header_slug = request.META.get(HEADER_NAME)
    store = _lookup_store_by_slug(header_slug)
    if store is not None:
        return store, "header"

    # 3. Cookie.
    cookie_slug = request.COOKIES.get(COOKIE_NAME)
    store = _lookup_store_by_slug(cookie_slug)
    if store is not None:
        return store, "cookie"

    # 4. Fallback.
    return _fallback_store(), "fallback"


class _StoreDescriptor:
    """Descriptor that lazily resolves and caches ``request.store``.

    The resolver might run before ``resolver_match`` is populated (the
    middleware fires before URL dispatch). Using a descriptor means the
    URL-kwarg branch sees ``resolver_match`` the first time a view actually
    reads ``request.store``.
    """

    def __get__(self, request, _owner=None):
        if request is None:
            return self
        cached = getattr(request, "_cached_store", None)
        if cached is not None:
            return cached
        store, source = _resolve_store(request)
        request._cached_store = store
        request._cached_store_source = source
        return store


class CurrentStoreMiddleware:
    """Attaches ``request.store`` and persists the header-driven choice as a cookie."""

    def __init__(self, get_response):
        self.get_response = get_response
        # Patch ``HttpRequest.store`` lazily once per process — the
        # descriptor caches per-request and is idempotent under re-import.
        from django.http import HttpRequest

        if not isinstance(getattr(HttpRequest, "store", None), _StoreDescriptor):
            HttpRequest.store = _StoreDescriptor()  # type: ignore[attr-defined]

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Force the descriptor to resolve now so we know how the store was
        # chosen (the cookie-write side-effect cares about ``source``).
        _ = request.store  # noqa: B018 — triggers descriptor
        source = getattr(request, "_cached_store_source", "fallback")
        response = self.get_response(request)
        store = getattr(request, "_cached_store", None)
        if store is not None and source == "header":
            # Cross-tab persistence: a tab that sets the header on its first
            # request seeds the cookie so subsequent tabs without the header
            # still resolve to the same store via step 3 of the resolver.
            response.set_cookie(
                COOKIE_NAME,
                store.slug,
                max_age=_COOKIE_MAX_AGE,
                samesite="Lax",
                secure=False,
                httponly=False,
                path="/",
            )
        return response


class CustomerSessionMiddleware:
    """Resolves `request.customer` from the signed `pd_customer_session` cookie.

    Runs *after* ``CurrentStoreMiddleware`` so we can compare the cookie's
    store binding against ``request.store``. A mismatched / expired /
    tampered cookie sets ``request.customer = None`` and the response
    deletes the cookie so the next request starts clean.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw = request.COOKIES.get(CUSTOMER_COOKIE_NAME)
        request.customer = None
        request._customer_cookie_should_clear = False  # type: ignore[attr-defined]

        if raw:
            payload = unsign_customer_session(raw)
            if payload is None:
                # Bad signature / expired — flag the cookie for deletion.
                request._customer_cookie_should_clear = True  # type: ignore[attr-defined]
            else:
                # Store-binding check — cookie must match the currently
                # resolved store (URL slug wins on /s/<slug>/... routes).
                store = request.store
                if store is None or store.id != payload["store_id"]:
                    request._customer_cookie_should_clear = True  # type: ignore[attr-defined]
                else:
                    from .models import Customer

                    customer = Customer.objects.filter(
                        pk=payload["customer_id"], store_id=store.id
                    ).first()
                    if customer is None:
                        request._customer_cookie_should_clear = True  # type: ignore[attr-defined]
                    else:
                        request.customer = customer

        response = self.get_response(request)
        if getattr(request, "_customer_cookie_should_clear", False):
            response.delete_cookie(CUSTOMER_COOKIE_NAME, path="/")
        return response


# ---------------------------------------------------------------------------
# Staff-only gate (v10a) — see PRD .claude/prds/staff-auth.md
# ---------------------------------------------------------------------------

# URL prefix this middleware gates. Centralised constant so tests and the
# StaffSessionProvider docs reference one source of truth.
STAFF_ONLY_URL_PREFIX = "/api/admin/"


class StaffOnlyMiddleware:
    """Gate every ``/api/admin/*`` request on a staff Django session.

    Reverses the project's historical "no API-level permission gates"
    convention — but ONLY for ``/api/admin/*``. Customer endpoints
    (``/api/me/*``, ``/api/quote/``, ``/api/c/<token>/``, ``/api/bookings/``)
    are NOT touched and keep their customer-cookie / public semantics.
    See PRD ``.claude/prds/staff-auth.md`` for the rationale: the
    convention made sense when there was no real auth, but now there
    is, and the admin URLs should fail closed by default.

    Behaviour:
      - Anonymous request to ``/api/admin/*`` → 401 JSON.
      - Authenticated non-staff request → 403 JSON.
      - Staff request → pass through.
      - Anything else → pass through unchanged.

    Must run AFTER ``django.contrib.auth.middleware.AuthenticationMiddleware``
    (so ``request.user`` is populated) and AFTER ``CurrentStoreMiddleware``
    (so admin views still see ``request.store``).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith(STAFF_ONLY_URL_PREFIX):
            user = getattr(request, "user", None)
            if user is None or not user.is_authenticated:
                return JsonResponse({"detail": "Authentication required."}, status=401)
            if not user.is_staff:
                return JsonResponse({"detail": "Staff access required."}, status=403)
        return self.get_response(request)
