"""
Strategy registry — the one place that knows about every concrete rule type.

Adding a new rule type:
  1. Write `pricing/strategies/<rule_type>.py` with a `RuleStrategy` subclass.
  2. Add the new ``rule_type`` choice to `pricing.models.RuleType`.
  3. Add the new entry below.

The engine in ``pricing/engine.py`` reads from ``RULE_REGISTRY`` and is
agnostic to every concrete type.
"""

from .base import QuoteContext, RuleStrategy
from .bracket_rate import BracketRateStrategy
from .day_of_week import DayOfWeekStrategy
from .member_tier import MemberTierStrategy
from .min_duration import MinDurationStrategy
from .peak_hours import PeakHoursStrategy

RULE_REGISTRY: dict[str, RuleStrategy] = {
    "peak_hours": PeakHoursStrategy(),
    "day_of_week": DayOfWeekStrategy(),
    "member_tier": MemberTierStrategy(),
    "min_duration": MinDurationStrategy(),
    "bracket_rate": BracketRateStrategy(),
}

__all__ = [
    "QuoteContext",
    "RuleStrategy",
    "RULE_REGISTRY",
    "PeakHoursStrategy",
    "DayOfWeekStrategy",
    "MemberTierStrategy",
    "MinDurationStrategy",
    "BracketRateStrategy",
]
