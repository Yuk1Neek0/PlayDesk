"""
bracket_rate strategy — tiered per-hour rate that overrides the base total.

params shape:
    {
        "brackets": [
            {"max_hours": 2, "rate": "50.00"},
            {"max_hours": null, "rate": "30.00"},   # last bracket = open-ended
        ]
    }

Math: for an N-hour booking, walk the brackets in order, consuming
``min(remaining_hours, bracket_size)`` at each bracket's ``rate``. The last
bracket may carry ``max_hours: null`` to absorb anything remaining.

Returns ``desired_total - running_total`` (override semantics).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from .base import QuoteContext, RuleStrategy, ValidationError

if TYPE_CHECKING:
    from pricing.models import PricingRule


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class BracketRateStrategy(RuleStrategy):
    @classmethod
    def params_schema(cls) -> dict:
        return {
            "type": "object",
            "required": ["brackets"],
            "properties": {
                "brackets": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["max_hours", "rate"],
                        "properties": {
                            "max_hours": {"type": ["integer", "null"], "minimum": 1},
                            "rate": {"type": ["number", "string"]},
                        },
                    },
                }
            },
        }

    @classmethod
    def validate_params(cls, params: dict) -> None:
        if not isinstance(params, dict):
            raise ValidationError("params must be an object")
        brackets = params.get("brackets")
        if not isinstance(brackets, list) or not brackets:
            raise ValidationError("brackets must be a non-empty list")
        for idx, b in enumerate(brackets):
            if not isinstance(b, dict):
                raise ValidationError(f"bracket[{idx}] must be an object")
            mh = b.get("max_hours")
            if mh is not None and (not isinstance(mh, int) or mh < 1):
                raise ValidationError(f"bracket[{idx}].max_hours must be null or a positive int")
            if "rate" not in b:
                raise ValidationError(f"bracket[{idx}] missing rate")
            try:
                _to_decimal(b["rate"])
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError(f"bracket[{idx}].rate must be a number") from None

    def applies(self, rule: PricingRule, ctx: QuoteContext) -> bool:
        # Always applies when the rule is active. Resource scoping is enforced
        # by the engine (it filters to ``applies_to_resource is None OR ==
        # resource``).
        return True

    def compute(self, rule: PricingRule, ctx: QuoteContext, running_total: Decimal) -> Decimal:
        remaining = ctx.hours
        desired = Decimal("0")
        prior_cap = Decimal("0")
        for bracket in rule.params["brackets"]:
            if remaining <= 0:
                break
            rate = _to_decimal(bracket["rate"])
            mh = bracket.get("max_hours")
            if mh is None:
                # Open-ended last bracket — absorb whatever's left.
                consume = remaining
            else:
                cap = Decimal(str(mh))
                bracket_size = cap - prior_cap
                if bracket_size <= 0:
                    continue
                consume = min(remaining, bracket_size)
                prior_cap = cap
            desired += consume * rate
            remaining -= consume
        return desired - running_total
