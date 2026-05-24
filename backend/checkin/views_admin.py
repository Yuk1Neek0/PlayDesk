"""Admin /api/admin/checkin/* endpoints (v11a, task #207).

Gated automatically by `core.middleware.StaffOnlyMiddleware` because
every path matches `/api/admin/*`. No per-view auth class needed.

  - GET   /api/admin/checkin/active-key/   current key + QR URL
  - POST  /api/admin/checkin/rotate/       force-mint a new key
  - PATCH /api/admin/checkin/settings/     update rotation_minutes

All three operate on `request.store` (set by `CurrentStoreMiddleware`),
so the admin store-switcher transparently scopes the response.
"""

from __future__ import annotations

from django.conf import settings as dj_settings
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import get_active_key, mint_key


def _key_payload(store, key) -> dict:
    qr_url = f"{dj_settings.SITE_URL}/c-in/?k={key.key}"
    return {
        "key": key.key,
        "created_at": key.created_at.isoformat(),
        "expires_at": key.expires_at.isoformat(),
        "rotation_minutes": store.checkin_rotation_minutes,
        "qr_url": qr_url,
    }


def _no_store_response() -> Response:
    return Response({"detail": "No store selected."}, status=status.HTTP_400_BAD_REQUEST)


class AdminActiveKeyView(APIView):
    """GET /api/admin/checkin/active-key/ — current rotating key for this store.

    Mints one on first call so the settings page always has something
    to show even on a fresh deployment that hasn't run cron yet.
    """

    def get(self, request):
        store = getattr(request, "store", None)
        if store is None:
            return _no_store_response()
        active = get_active_key(store)
        if active is None:
            active = mint_key(store)
        return Response(_key_payload(store, active))


class AdminRotateNowView(APIView):
    """POST /api/admin/checkin/rotate/ — staff force-rotate."""

    def post(self, request):
        store = getattr(request, "store", None)
        if store is None:
            return _no_store_response()
        new = mint_key(store)
        return Response(_key_payload(store, new), status=status.HTTP_201_CREATED)


class _SettingsSerializer(serializers.Serializer):
    rotation_minutes = serializers.IntegerField(min_value=1, max_value=60)


class AdminSettingsView(APIView):
    """PATCH /api/admin/checkin/settings/ — update rotation_minutes."""

    def patch(self, request):
        store = getattr(request, "store", None)
        if store is None:
            return _no_store_response()
        ser = _SettingsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        store.checkin_rotation_minutes = ser.validated_data["rotation_minutes"]
        store.save(update_fields=["checkin_rotation_minutes"])
        active = get_active_key(store)
        if active is None:
            active = mint_key(store)
        return Response(_key_payload(store, active))
