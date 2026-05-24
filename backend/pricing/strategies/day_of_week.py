"""
day_of_week strategy — flat rate or discount on selected weekdays.

params shape (one of):
    {"days": ["tue", ...], "flat_rate": "30.00"}     # override semantics
    {"days": ["tue", ...], "discount_pct": 20}       # discount semantics
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from .base import QuoteContext, RuleStrategy, ValidationError

if TYPE_CHECKING:
    from pricing.models import PricingRule


_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _to_decimal(value) -> Decimal:
    """Coerce ints / floats / strings to Decimal via str() to avoid float drift."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class DayOfWeekStrategy(RuleStrategy):
    @classmethod
    def params_schema(cls) -> dict:
        return {
            "type": "object",
            "required": ["days"],
            "properties": {
                "days": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_DAY_NAMES)},
                    "minItems": 1,
                },
                "flat_rate": {"type": ["number", "string"]},
                "discount_pct": {"type": "integer"},
            },
            "oneOf": [{"required": ["flat_rate"]}, {"required": ["discount_pct"]}],
        }

    @classmethod
    def validate_params(cls, params: dict) -> None:
        if not isinstance(params, dict):
            raise ValidationError("params must be an object")
        days = params.get("days")
        if not isinstance(days, list) or not days:
            raise ValidationError("days must be a non-empty list")
        for d in days:
            if d not in _DAY_NAMES:
                raise ValidationError(f"unknown day: {d}")
        has_flat = "flat_rate" in params
        has_pct = "discount_pct" in params
        if has_flat == has_pct:
            raise ValidationError("exactly one of flat_rate or discount_pct is required")
        if has_flat:
            try:
                _to_decimal(params["flat_rate"])
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError("flat_rate must be a number") from None
        else:
            if not isinstance(params["discount_pct"], int):
                raise ValidationError("discount_pct must be an int")

    def applies(self, rule: PricingRule, ctx: QuoteContext) -> bool:
        params = rule.params or {}
        day_name = _DAY_NAMES[ctx.start_at.weekday()]
        return day_name in (params.get("days") or [])

    def compute(self, rule: PricingRule, ctx: QuoteContext, running_total: Decimal) -> Decimal:
        params = rule.params
        if "flat_rate" in params:
            # Override semantics: the desired total is flat_rate * hours.
            desired = _to_decimal(params["flat_rate"]) * ctx.hours
            return desired - running_total
        pct = Decimal(str(params["discount_pct"]))
        return -running_total * (pct / Decimal("100"))
