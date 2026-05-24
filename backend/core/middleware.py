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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


COOKIE_NAME = "pd_store_slug"
HEADER_NAME = "HTTP_X_PD_STORE_SLUG"
# 1 year — admin sessions are durable and the cookie is just a preference.
_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


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
