"""
min_duration strategy — package-deal discount when the booking meets a min
length.

params shape:
    {"min_hours": int, "discount_pct": int}
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from .base import QuoteContext, RuleStrategy, ValidationError

if TYPE_CHECKING:
    from pricing.models import PricingRule


class MinDurationStrategy(RuleStrategy):
    @classmethod
    def params_schema(cls) -> dict:
        return {
            "type": "object",
            "required": ["min_hours", "discount_pct"],
            "properties": {
                "min_hours": {"type": "integer", "minimum": 1},
                "discount_pct": {"type": "integer", "minimum": 0, "maximum": 100},
            },
        }

    @classmethod
    def validate_params(cls, params: dict) -> None:
        if not isinstance(params, dict):
            raise ValidationError("params must be an object")
        mh = params.get("min_hours")
        if not isinstance(mh, int) or mh < 1:
            raise ValidationError("min_hours must be a positive int")
        pct = params.get("discount_pct")
        if not isinstance(pct, int) or pct < 0 or pct > 100:
            raise ValidationError("discount_pct must be an int 0..100")

    def applies(self, rule: PricingRule, ctx: QuoteContext) -> bool:
        min_hours = Decimal(str(rule.params.get("min_hours", 0)))
        return ctx.hours >= min_hours

    def compute(self, rule: PricingRule, ctx: QuoteContext, running_total: Decimal) -> Decimal:
        pct = Decimal(str(rule.params["discount_pct"]))
        return -running_total * (pct / Decimal("100"))
