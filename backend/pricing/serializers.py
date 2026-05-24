"""
DRF serializers for the pricing app: ``/api/quote/`` input + the public
admin ``PricingRule`` shape used by ``/api/admin/pricing-rules/`` in task
177.
"""

from rest_framework import serializers

from core.models import Customer, Resource

from .models import PricingRule, RuleType
from .strategies import RULE_REGISTRY


class QuoteRequestSerializer(serializers.Serializer):
    """Input validator for POST /api/quote/."""

    resource_id = serializers.IntegerField()
    start_at = serializers.DateTimeField()
    end_at = serializers.DateTimeField()
    customer_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs):
        if attrs["end_at"] <= attrs["start_at"]:
            raise serializers.ValidationError({"end_at": "end_at must be after start_at."})
        return attrs


class PricingRuleSerializer(serializers.ModelSerializer):
    """Admin-facing CRUD shape for ``PricingRule``.

    Validates ``params`` against the strategy's schema on write — bad
    shapes 400 instead of silently misbehaving at quote time.
    """

    applies_to_resource_id = serializers.PrimaryKeyRelatedField(
        queryset=Resource.objects.all(),
        source="applies_to_resource",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = PricingRule
        fields = [
            "id",
            "name",
            "description",
            "enabled",
            "priority",
            "stackable",
            "rule_type",
            "params",
            "applies_to_resource_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        # Find the effective rule_type + params (PATCH may omit either).
        rule_type = attrs.get("rule_type") or (self.instance.rule_type if self.instance else None)
        params = attrs.get("params")
        if params is None and self.instance is not None:
            params = self.instance.params
        if rule_type not in {choice[0] for choice in RuleType.choices}:
            raise serializers.ValidationError({"rule_type": f"Unknown rule_type: {rule_type}"})
        strategy = RULE_REGISTRY[rule_type]
        try:
            strategy.validate_params(params or {})
        except Exception as exc:  # noqa: BLE001 — Django ValidationError or similar
            raise serializers.ValidationError({"params": str(exc)}) from None
        return attrs


__all__ = ["QuoteRequestSerializer", "PricingRuleSerializer", "Customer"]
