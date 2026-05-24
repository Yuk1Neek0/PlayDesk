"""
peak_hours strategy — surcharge / discount during a window on selected weekdays.

params shape:
    {
        "days": ["mon", "tue", ...],   # any subset of mon..sun
        "start_hour": 0..24,           # inclusive
        "end_hour": 0..24,             # exclusive; > start_hour
        "adjustment_pct": int,         # signed; +20 = +20% surcharge, -10 = -10% discount
    }
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from .base import QuoteContext, RuleStrategy, ValidationError

if TYPE_CHECKING:
    from pricing.models import PricingRule


_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class PeakHoursStrategy(RuleStrategy):
    @classmethod
    def params_schema(cls) -> dict:
        return {
            "type": "object",
            "required": ["days", "start_hour", "end_hour", "adjustment_pct"],
            "properties": {
                "days": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_DAY_NAMES)},
                    "minItems": 1,
                },
                "start_hour": {"type": "integer", "minimum": 0, "maximum": 24},
                "end_hour": {"type": "integer", "minimum": 0, "maximum": 24},
                "adjustment_pct": {"type": "integer"},
            },
        }

    @classmethod
    def validate_params(cls, params: dict) -> None:
        if not isinstance(params, dict):
            raise ValidationError("params must be an object")
        for key in ("days", "start_hour", "end_hour", "adjustment_pct"):
            if key not in params:
                raise ValidationError(f"missing required key: {key}")
        days = params["days"]
        if not isinstance(days, list) or not days:
            raise ValidationError("days must be a non-empty list")
        for d in days:
            if d not in _DAY_NAMES:
                raise ValidationError(f"unknown day: {d}")
        for hkey in ("start_hour", "end_hour"):
            h = params[hkey]
            if not isinstance(h, int) or h < 0 or h > 24:
                raise ValidationError(f"{hkey} must be an int 0..24")
        if params["end_hour"] <= params["start_hour"]:
            raise ValidationError("end_hour must be > start_hour")
        if not isinstance(params["adjustment_pct"], int):
            raise ValidationError("adjustment_pct must be an int")

    def applies(self, rule: PricingRule, ctx: QuoteContext) -> bool:
        params = rule.params or {}
        weekday_idx = ctx.start_at.weekday()
        day_name = _DAY_NAMES[weekday_idx]
        if day_name not in (params.get("days") or []):
            return False
        hour = ctx.start_at.hour
        return params["start_hour"] <= hour < params["end_hour"]

    def compute(self, rule: PricingRule, ctx: QuoteContext, running_total: Decimal) -> Decimal:
        pct = Decimal(str(rule.params["adjustment_pct"]))
        return running_total * (pct / Decimal("100"))
