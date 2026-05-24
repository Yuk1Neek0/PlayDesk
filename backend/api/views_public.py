"""
Public (no-auth) views for branding signals consumed by the customer-facing
Next.js surfaces (booking page, QR landing page).

These intentionally live in their own module to keep the auth posture obvious:
nothing here is gated, everything here is cached, and everything here returns
the smallest possible payload needed by an SSR render.
"""

import re

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Store

# Tiny CSS-value grammar for `Store.brand.accent`. We accept the three formats
# actually documented for the field (oklch(...), #RRGGBB, rgb(...)). Anything
# else — including `javascript:`, raw words, malformed parens — is rejected and
# the response carries `accent: null` so the frontend falls back to default.
_ACCENT_RE = re.compile(r"^(oklch\([^)]+\)|#[0-9A-Fa-f]{6}|rgb\([^)]+\))$")


def _validated_accent(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    return raw if _ACCENT_RE.match(raw) else None


class StoreBrandView(APIView):
    """GET /api/public/store-brand/ — current store's branding fields.

    Resolution order for which store to brand:
      1. ``?store=<slug>`` query param (explicit caller intent — the new
         ``/s/[slug]/book`` SSR loader uses this so the URL store's brand
         renders regardless of cookie state).
      2. ``request.store`` (the ``CurrentStoreMiddleware`` chain — header,
         cookie, or alphabetically-first fallback).

    The fallback preserves the legacy single-store behaviour for callers
    without a slug context.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        slug = request.GET.get("store")
        store = None
        if slug:
            store = Store.objects.filter(slug=slug).first()
        if store is None:
            store = request.store
        if store is None:
            payload = {"name": "PlayDesk", "logo_url": None, "accent": None}
        else:
            brand = store.brand or {}
            logo_url = brand.get("logo_url")
            payload = {
                "name": store.name,
                "logo_url": logo_url if isinstance(logo_url, str) and logo_url else None,
                "accent": _validated_accent(brand.get("accent")),
            }
        resp = Response(payload, status=status.HTTP_200_OK)
        resp["Cache-Control"] = "public, max-age=60"
        return resp


class DefaultStoreView(APIView):
    """GET /api/public/default-store/ — slug of the default store.

    Returns ``{"slug": <slug>}`` for the alphabetically-first ``Store``
    (matches ``CurrentStoreMiddleware``'s fallback). Powers the root-page
    302 redirect to ``/s/<default>/book`` so a multi-store deployment that
    later drops its flagship still resolves the default correctly without
    a frontend redeploy.

    Empty-deployment safety: returns ``{"slug": null}`` when no stores
    exist. The caller renders a sensible fallback rather than 5xxing.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        store = Store.objects.order_by("slug").first()
        payload = {"slug": store.slug if store is not None else None}
        resp = Response(payload, status=status.HTTP_200_OK)
        resp["Cache-Control"] = "public, max-age=60"
        return resp
