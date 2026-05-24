"""
Strategy ABC + the shared QuoteContext dataclass.

Each rule_type has a `RuleStrategy` subclass under `pricing/strategies/`
(one file per type) that knows:

  * `params_schema()`     — a minimal JSON Schema-ish dict for admin form
                             generation and server-side validation.
  * `validate_params()`   — raises ``ValidationError`` on bad shape.
  * `applies(rule, ctx)`  — does this rule fire for this booking?
  * `compute(rule, ctx, running_total)` — signed Decimal adjustment.

The engine itself in ``pricing/engine.py`` is rule-type-agnostic: it loops
over rules, looks up the strategy via ``RULE_REGISTRY[rule.rule_type]``,
and accumulates signed adjustments.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from core.models import Customer, Resource, RewardTier
    from pricing.models import PricingRule


@dataclass
class QuoteContext:
    """Per-quote context passed to every strategy.

    All fields are immutable for the duration of the quote evaluation; the
    running total is threaded into ``RuleStrategy.compute`` directly because
    each rule's adjustment may depend on the prior rules' effect.
    """

    resource: Resource
    start_at: datetime
    end_at: datetime
    customer: Customer | None
    customer_tier: RewardTier | None
    hours: Decimal
    base_amount: Decimal


class RuleStrategy(ABC):
    """Abstract per-rule-type evaluator.

    Subclasses live in `pricing/strategies/<rule_type>.py`. Add a new
    rule type by writing one file + adding one entry to ``RULE_REGISTRY``
    in ``pricing/strategies/__init__.py``.
    """

    @classmethod
    @abstractmethod
    def params_schema(cls) -> dict:
        """Return a minimal JSON-schema dict describing the params shape.

        Used by the admin form generator (task #177) AND by
        ``validate_params``. Keep it small — the v8 schemas are simple
        flat dicts.
        """

    @classmethod
    @abstractmethod
    def validate_params(cls, params: dict) -> None:
        """Raise ``django.core.exceptions.ValidationError`` on bad shape."""

    @abstractmethod
    def applies(self, rule: PricingRule, ctx: QuoteContext) -> bool:
        """Does this rule fire for this booking?"""

    @abstractmethod
    def compute(self, rule: PricingRule, ctx: QuoteContext, running_total: Decimal) -> Decimal:
        """Return the signed Decimal adjustment to apply.

        Negative values are discounts; positive values are surcharges.
        For "override" semantics (bracket_rate, day_of_week-with-flat-rate)
        return ``desired_total - running_total``.
        """


# Re-export so callers can ``from pricing.strategies.base import ValidationError``.
__all__ = ["QuoteContext", "RuleStrategy", "ValidationError"]
