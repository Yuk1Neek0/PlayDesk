"""Admin endpoints for the outbound message log.

`GET /api/admin/outbound/?customer_id=N&limit=20` — per-customer log,
newest-first. Powers the "Outbound messages" card on the customer
detail page.

`GET /api/admin/outbound/?status=failed&limit=50` — failure inspection
across all customers (ops triage; no frontend page consumes it in v4).
"""

from __future__ import annotations

from rest_framework import serializers
from rest_framework.generics import ListAPIView

from outbound.models import OutboundMessage, OutboundStatus


class OutboundMessageSerializer(serializers.ModelSerializer):
    customer_id = serializers.IntegerField(source="customer.id", read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)

    class Meta:
        model = OutboundMessage
        fields = [
            "id",
            "customer_id",
            "customer_name",
            "customer_phone",
            "channel",
            "template_key",
            "body",
            "status",
            "scheduled_for",
            "sent_at",
            "failure_reason",
            "provider_message_id",
            "created_at",
        ]


class OutboundMessageListView(ListAPIView):
    """`GET /api/admin/outbound/`.

    Filters (one of):
      - `?customer_id=N` — per-customer log, newest-first.
      - `?status=failed` — failures across customers, newest-first.
    `?limit=N` caps the result (default 20 for customer view, 50 for
    failure view; hard-capped at 200).
    """

    serializer_class = OutboundMessageSerializer
    pagination_class = None  # Operator-driven list, not a paginated UI.

    def get_queryset(self):
        params = self.request.query_params
        customer_id = params.get("customer_id")
        status_filter = params.get("status")
        try:
            default_limit = 20 if customer_id else 50
            limit = int(params.get("limit") or default_limit)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(limit, 200))

        qs = OutboundMessage.objects.select_related("customer", "customer__store")
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        if status_filter:
            # Only allow real status values.
            if status_filter in {s.value for s in OutboundStatus}:
                qs = qs.filter(status=status_filter)
        return qs.order_by("-created_at")[:limit]
