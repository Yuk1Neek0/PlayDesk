"""
Views for the pricing app: the public ``POST /api/quote/`` endpoint and the
admin ``/api/admin/pricing-rules/`` CRUD (task 177).
"""

from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Customer, Resource

from .engine import compute_quote
from .models import PricingRule
from .serializers import PricingRuleSerializer, QuoteRequestSerializer


class QuoteView(APIView):
    """POST /api/quote/ — public, no auth.

    Body: ``{resource_id, start_at, end_at, customer_id?}``.

    Returns ``{base_amount, line_items[], total_amount, rule_snapshot[]}``
    so the booking page can render the breakdown live as the user picks a
    slot. Used identically by the agent's ``check_availability`` tool to
    quote each candidate slot.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        ser = QuoteRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Resource lookup is store-scoped via ``request.store`` — quoting a
        # resource that belongs to another store returns 404 so cross-store
        # ids can't be enumerated.
        qs = Resource.objects.select_related("store")
        store = getattr(request, "store", None)
        if store is not None:
            qs = qs.filter(store=store)
        try:
            resource = qs.get(pk=data["resource_id"])
        except Resource.DoesNotExist:
            return Response({"detail": "Resource not found."}, status=status.HTTP_404_NOT_FOUND)

        customer = None
        customer_id = data.get("customer_id")
        if customer_id:
            customer = Customer.objects.filter(pk=customer_id, store=resource.store).first()

        quote = compute_quote(
            resource,
            data["start_at"],
            data["end_at"],
            customer=customer,
        )
        return Response(quote.to_dict(), status=status.HTTP_200_OK)


class PricingRuleViewSet(viewsets.ModelViewSet):
    """CRUD ``/api/admin/pricing-rules/`` — task 177.

    Store-scoped via ``request.store`` (mirrors v4 rewards/tiers). No
    permission classes per PlayDesk admin-API convention; auth handled
    by the admin shell.
    """

    serializer_class = PricingRuleSerializer
    authentication_classes: list = []
    permission_classes: list = []

    def get_queryset(self):
        qs = PricingRule.objects.select_related("applies_to_resource")
        store = getattr(self.request, "store", None)
        if store is not None:
            qs = qs.filter(store=store)
        return qs.order_by("priority", "id")

    def perform_create(self, serializer):
        store = getattr(self.request, "store", None)
        serializer.save(store=store)


__all__ = ["QuoteView", "PricingRuleViewSet"]
