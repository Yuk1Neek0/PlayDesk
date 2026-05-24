"""Admin endpoint that powers the frontend store-switcher.

``GET /api/admin/stores/`` returns the full set of ``Store`` rows trimmed
to the fields the chip-group selector renders: ``id``, ``slug``, ``name``.
Sorted alphabetically by ``slug`` so the chip order is deterministic and
matches the middleware's fallback resolution.

Auth posture matches the rest of the admin surface in v6 — no API-level
permission gate; the admin frontend mounts the call behind its session.
"""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Store


class AdminStoreListView(APIView):
    """GET /api/admin/stores/ — list of stores for the store switcher."""

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        stores = list(Store.objects.order_by("slug").values("id", "slug", "name"))
        return Response(stores)
