"""
member_tier strategy — % discount when the customer's tier matches.

params shape:
    {"tier_id": int, "discount_pct": int}
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from .base import QuoteContext, RuleStrategy, ValidationError

if TYPE_CHECKING:
    from pricing.models import PricingRule


class MemberTierStrategy(RuleStrategy):
    @classmethod
    def params_schema(cls) -> dict:
        return {
            "type": "object",
            "required": ["tier_id", "discount_pct"],
            "properties": {
                "tier_id": {"type": "integer", "minimum": 1},
                "discount_pct": {"type": "integer", "minimum": 0, "maximum": 100},
            },
        }

    @classmethod
    def validate_params(cls, params: dict) -> None:
        if not isinstance(params, dict):
            raise ValidationError("params must be an object")
        tier_id = params.get("tier_id")
        if not isinstance(tier_id, int) or tier_id < 1:
            raise ValidationError("tier_id must be a positive int")
        pct = params.get("discount_pct")
        if not isinstance(pct, int) or pct < 0 or pct > 100:
            raise ValidationError("discount_pct must be an int 0..100")

    def applies(self, rule: PricingRule, ctx: QuoteContext) -> bool:
        if ctx.customer_tier is None:
            return False
        return ctx.customer_tier.id == rule.params.get("tier_id")

    def compute(self, rule: PricingRule, ctx: QuoteContext, running_total: Decimal) -> Decimal:
        pct = Decimal(str(rule.params["discount_pct"]))
        return -running_total * (pct / Decimal("100"))
