"""DRF views for the v4 memberships epic.

Five admin endpoints:
  - GET  /api/admin/customers/{id}/membership/
  - POST /api/admin/customers/{id}/adjust-points/
  - POST /api/admin/customers/{id}/redeem/
  - /api/admin/rewards/ (ViewSet)
  - /api/admin/tiers/   (ViewSet)

All five are gated behind ``IsAdminUser``. The membership read endpoint
funnels into a single composite payload sized for the customer-detail
page render — balance, tier badge, next-tier hint, last 20 ledger rows,
and the catalogue of rewards the customer can currently afford.
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.memberships import (
    award_points,
    current_balance,
    lifetime_points_earned,
    next_tier_for,
    tier_for,
)
from core.models import Customer, PointTransaction, Reward, RewardTier

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class PointTransactionSerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source="author.username", read_only=True, default=None)

    class Meta:
        model = PointTransaction
        fields = [
            "id",
            "delta",
            "source",
            "reference",
            "balance_after",
            "author_username",
            "created_at",
        ]
        read_only_fields = fields


class RewardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reward
        fields = ["id", "store", "name", "description", "cost_points", "enabled", "created_at"]
        read_only_fields = ["id", "created_at"]


class RewardTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = RewardTier
        fields = ["id", "store", "name", "min_lifetime_points", "perks_text", "position"]
        read_only_fields = ["id"]


class AdjustPointsSerializer(serializers.Serializer):
    delta = serializers.IntegerField()
    reason = serializers.CharField()

    def validate_delta(self, value: int) -> int:
        if value == 0:
            raise serializers.ValidationError("delta must be non-zero")
        return value

    def validate_reason(self, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise serializers.ValidationError("reason is required")
        return cleaned


class RedeemSerializer(serializers.Serializer):
    reward_id = serializers.IntegerField()


# ---------------------------------------------------------------------------
# Membership composite view
# ---------------------------------------------------------------------------


class MembershipView(APIView):
    """GET /api/admin/customers/{id}/membership/."""

    permission_classes = [IsAdminUser]

    def get(self, request, pk: int):
        customer = get_object_or_404(Customer, pk=pk)
        balance = current_balance(customer)
        lifetime = lifetime_points_earned(customer)
        tier = tier_for(customer)
        nxt = next_tier_for(customer)

        recent = list(
            PointTransaction.objects.filter(customer=customer)
            .select_related("author")
            .order_by("-created_at", "-id")[:20]
        )
        available = list(
            Reward.objects.filter(
                store_id=customer.store_id, enabled=True, cost_points__lte=balance
            ).order_by("cost_points", "name")
        )

        return Response(
            {
                "customer_id": customer.id,
                "balance": balance,
                "lifetime_earned": lifetime,
                "tier": (
                    {"id": tier.id, "name": tier.name, "perks_text": tier.perks_text}
                    if tier
                    else None
                ),
                "next_tier": (
                    {
                        "id": nxt.id,
                        "name": nxt.name,
                        "min_lifetime_points": nxt.min_lifetime_points,
                    }
                    if nxt
                    else None
                ),
                "points_to_next_tier": (
                    max(0, nxt.min_lifetime_points - lifetime) if nxt else None
                ),
                "recent_transactions": PointTransactionSerializer(recent, many=True).data,
                "available_rewards": RewardSerializer(available, many=True).data,
            }
        )


# ---------------------------------------------------------------------------
# Adjust points
# ---------------------------------------------------------------------------


class AdjustPointsView(APIView):
    """POST /api/admin/customers/{id}/adjust-points/."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk: int):
        customer = get_object_or_404(Customer, pk=pk)
        ser = AdjustPointsSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        author = request.user if request.user.is_authenticated else None
        pt = award_points(
            customer,
            ser.validated_data["delta"],
            "adjustment",
            ser.validated_data["reason"],
            author=author,
        )
        return Response(
            {"transaction_id": pt.id, "balance": pt.balance_after},
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Redeem
# ---------------------------------------------------------------------------


class RedeemView(APIView):
    """POST /api/admin/customers/{id}/redeem/.

    Atomic — balance check + debit transaction + Redemption row, all in
    one DB transaction so two concurrent redeem attempts can't both
    succeed past the balance.
    """

    permission_classes = [IsAdminUser]

    def post(self, request, pk: int):
        customer = get_object_or_404(Customer, pk=pk)
        ser = RedeemSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            reward = Reward.objects.get(
                pk=ser.validated_data["reward_id"], store_id=customer.store_id, enabled=True
            )
        except Reward.DoesNotExist:
            raise ValidationError({"reward_id": "Reward not found or not available."})

        with transaction.atomic():
            # award_points takes select_for_update on the customer, so a
            # concurrent redeem on the same customer serialises here.
            Customer.objects.select_for_update().filter(pk=customer.pk).first()
            balance = current_balance(customer)
            if balance < reward.cost_points:
                return Response(
                    {
                        "error": "insufficient_points",
                        "balance": balance,
                        "cost": reward.cost_points,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            staff = request.user if request.user.is_authenticated else None
            pt = award_points(
                customer,
                -reward.cost_points,
                "redemption",
                reference=str(reward.id),
                author=staff,
            )
            from core.models import Redemption

            redemption = Redemption.objects.create(
                customer=customer, reward=reward, transaction=pt, staff=staff
            )

        return Response(
            {
                "redemption_id": redemption.id,
                "transaction_id": pt.id,
                "balance": pt.balance_after,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Rewards / Tiers CRUD (store-scoped via ?store= filter)
# ---------------------------------------------------------------------------


class RewardViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]
    serializer_class = RewardSerializer

    def get_queryset(self):
        qs = Reward.objects.all().order_by("store_id", "cost_points", "name")
        store_id = self.request.query_params.get("store")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs


class RewardTierViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]
    serializer_class = RewardTierSerializer

    def get_queryset(self):
        qs = RewardTier.objects.all().order_by("store_id", "position")
        store_id = self.request.query_params.get("store")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs
