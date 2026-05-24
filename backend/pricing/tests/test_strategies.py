"""
Unit tests for the five v8 pricing strategies + the registry.

Each strategy is tested in isolation with a hand-built ``QuoteContext`` — no
DB fixtures are needed because strategies are pure functions of their rule
+ context (the engine is tested separately).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from pricing.strategies import (
    RULE_REGISTRY,
    BracketRateStrategy,
    DayOfWeekStrategy,
    MemberTierStrategy,
    MinDurationStrategy,
    PeakHoursStrategy,
    QuoteContext,
)

# ---------------------------------------------------------------------------
# Helpers — fake `rule` and `ctx` so strategies stay pure
# ---------------------------------------------------------------------------


def _rule(params: dict, **overrides):
    """Build a stand-in for a PricingRule row. The strategies only look at
    `.params`, so a SimpleNamespace is enough."""
    defaults = {"id": 1, "name": "Test rule", "stackable": True}
    defaults.update(overrides)
    return SimpleNamespace(params=params, **defaults)


def _ctx(
    *,
    start: datetime,
    end: datetime,
    hours: Decimal,
    base: Decimal,
    customer_tier=None,
):
    """Build a QuoteContext. Resource/customer aren't touched by the v8
    strategies (only ``customer_tier``); pass ``None`` placeholders."""
    return QuoteContext(
        resource=SimpleNamespace(id=1, store_id=1),  # type: ignore[arg-type]
        start_at=start,
        end_at=end,
        customer=None,
        customer_tier=customer_tier,
        hours=hours,
        base_amount=base,
    )


def _dt(year=2026, month=5, day=22, hour=20, minute=0) -> datetime:
    """Fri 2026-05-22 20:00 UTC by default (weekday()==4, "fri")."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# peak_hours
# ---------------------------------------------------------------------------


class TestPeakHours:
    def test_applies_inside_window(self):
        s = PeakHoursStrategy()
        rule = _rule(
            {"days": ["fri", "sat"], "start_hour": 20, "end_hour": 24, "adjustment_pct": 20}
        )
        ctx = _ctx(start=_dt(hour=20), end=_dt(hour=22), hours=Decimal("2"), base=Decimal("120"))
        assert s.applies(rule, ctx) is True

    def test_does_not_apply_outside_hours(self):
        s = PeakHoursStrategy()
        rule = _rule({"days": ["fri"], "start_hour": 20, "end_hour": 24, "adjustment_pct": 20})
        ctx = _ctx(start=_dt(hour=18), end=_dt(hour=19), hours=Decimal("1"), base=Decimal("60"))
        assert s.applies(rule, ctx) is False

    def test_does_not_apply_outside_days(self):
        s = PeakHoursStrategy()
        rule = _rule({"days": ["sat"], "start_hour": 20, "end_hour": 24, "adjustment_pct": 20})
        # Fri 2026-05-22
        ctx = _ctx(start=_dt(hour=20), end=_dt(hour=22), hours=Decimal("2"), base=Decimal("120"))
        assert s.applies(rule, ctx) is False

    def test_compute_positive_pct(self):
        s = PeakHoursStrategy()
        rule = _rule({"days": ["fri"], "start_hour": 20, "end_hour": 24, "adjustment_pct": 20})
        ctx = _ctx(start=_dt(hour=20), end=_dt(hour=22), hours=Decimal("2"), base=Decimal("120"))
        adj = s.compute(rule, ctx, Decimal("120"))
        # 20% of 120 = 24
        assert adj == Decimal("24.0")

    def test_compute_negative_pct(self):
        s = PeakHoursStrategy()
        rule = _rule({"days": ["mon"], "start_hour": 10, "end_hour": 18, "adjustment_pct": -10})
        ctx = _ctx(start=_dt(hour=10), end=_dt(hour=12), hours=Decimal("2"), base=Decimal("100"))
        adj = s.compute(rule, ctx, Decimal("100"))
        assert adj == Decimal("-10.0")

    def test_validate_params_ok(self):
        PeakHoursStrategy.validate_params(
            {"days": ["fri", "sat"], "start_hour": 20, "end_hour": 24, "adjustment_pct": 20}
        )

    def test_validate_params_rejects_unknown_day(self):
        with pytest.raises(ValidationError):
            PeakHoursStrategy.validate_params(
                {"days": ["funday"], "start_hour": 20, "end_hour": 24, "adjustment_pct": 20}
            )

    def test_validate_params_rejects_inverted_hours(self):
        with pytest.raises(ValidationError):
            PeakHoursStrategy.validate_params(
                {"days": ["fri"], "start_hour": 20, "end_hour": 20, "adjustment_pct": 0}
            )


# ---------------------------------------------------------------------------
# day_of_week
# ---------------------------------------------------------------------------


class TestDayOfWeek:
    def test_applies_on_matching_day(self):
        s = DayOfWeekStrategy()
        # 2026-05-26 is a Tuesday.
        rule = _rule({"days": ["tue"], "flat_rate": "30.00"})
        ctx = _ctx(
            start=_dt(2026, 5, 26, 12),
            end=_dt(2026, 5, 26, 14),
            hours=Decimal("2"),
            base=Decimal("120"),
        )
        assert s.applies(rule, ctx) is True

    def test_does_not_apply_off_day(self):
        s = DayOfWeekStrategy()
        rule = _rule({"days": ["tue"], "flat_rate": "30.00"})
        # Friday default
        ctx = _ctx(start=_dt(hour=20), end=_dt(hour=22), hours=Decimal("2"), base=Decimal("120"))
        assert s.applies(rule, ctx) is False

    def test_compute_flat_rate_override(self):
        s = DayOfWeekStrategy()
        # Cheap Tuesday: flat $30/hour. 2 hours, base 120 -> desired 60 -> adj -60.
        rule = _rule({"days": ["tue"], "flat_rate": "30.00"})
        ctx = _ctx(
            start=_dt(2026, 5, 26, 12),
            end=_dt(2026, 5, 26, 14),
            hours=Decimal("2"),
            base=Decimal("120"),
        )
        adj = s.compute(rule, ctx, Decimal("120"))
        assert adj == Decimal("-60.00")

    def test_compute_discount_pct(self):
        s = DayOfWeekStrategy()
        rule = _rule({"days": ["fri"], "discount_pct": 25})
        ctx = _ctx(start=_dt(hour=20), end=_dt(hour=22), hours=Decimal("2"), base=Decimal("120"))
        adj = s.compute(rule, ctx, Decimal("120"))
        assert adj == Decimal("-30.00")

    def test_validate_params_requires_one_of(self):
        with pytest.raises(ValidationError):
            DayOfWeekStrategy.validate_params({"days": ["tue"]})
        with pytest.raises(ValidationError):
            DayOfWeekStrategy.validate_params(
                {"days": ["tue"], "flat_rate": "30", "discount_pct": 20}
            )

    def test_validate_params_rejects_non_numeric_flat_rate(self):
        with pytest.raises(ValidationError):
            DayOfWeekStrategy.validate_params({"days": ["tue"], "flat_rate": "free"})


# ---------------------------------------------------------------------------
# member_tier
# ---------------------------------------------------------------------------


class TestMemberTier:
    def test_applies_on_matching_tier(self):
        s = MemberTierStrategy()
        tier = SimpleNamespace(id=3, name="Gold")
        rule = _rule({"tier_id": 3, "discount_pct": 15})
        ctx = _ctx(
            start=_dt(),
            end=_dt(hour=22),
            hours=Decimal("2"),
            base=Decimal("120"),
            customer_tier=tier,
        )
        assert s.applies(rule, ctx) is True

    def test_does_not_apply_on_other_tier(self):
        s = MemberTierStrategy()
        tier = SimpleNamespace(id=2, name="Silver")
        rule = _rule({"tier_id": 3, "discount_pct": 15})
        ctx = _ctx(
            start=_dt(),
            end=_dt(hour=22),
            hours=Decimal("2"),
            base=Decimal("120"),
            customer_tier=tier,
        )
        assert s.applies(rule, ctx) is False

    def test_does_not_apply_when_no_tier(self):
        s = MemberTierStrategy()
        rule = _rule({"tier_id": 3, "discount_pct": 15})
        ctx = _ctx(start=_dt(), end=_dt(hour=22), hours=Decimal("2"), base=Decimal("120"))
        assert s.applies(rule, ctx) is False

    def test_compute_discount(self):
        s = MemberTierStrategy()
        tier = SimpleNamespace(id=3, name="Gold")
        rule = _rule({"tier_id": 3, "discount_pct": 15})
        ctx = _ctx(
            start=_dt(),
            end=_dt(hour=22),
            hours=Decimal("2"),
            base=Decimal("80"),
            customer_tier=tier,
        )
        adj = s.compute(rule, ctx, Decimal("80"))
        assert adj == Decimal("-12.00")

    def test_validate_rejects_missing_tier(self):
        with pytest.raises(ValidationError):
            MemberTierStrategy.validate_params({"discount_pct": 15})

    def test_validate_rejects_bad_pct(self):
        with pytest.raises(ValidationError):
            MemberTierStrategy.validate_params({"tier_id": 3, "discount_pct": 150})


# ---------------------------------------------------------------------------
# min_duration
# ---------------------------------------------------------------------------


class TestMinDuration:
    def test_applies_when_hours_meet_min(self):
        s = MinDurationStrategy()
        rule = _rule({"min_hours": 3, "discount_pct": 20})
        ctx = _ctx(start=_dt(hour=18), end=_dt(hour=22), hours=Decimal("4"), base=Decimal("240"))
        assert s.applies(rule, ctx) is True

    def test_does_not_apply_below_min(self):
        s = MinDurationStrategy()
        rule = _rule({"min_hours": 3, "discount_pct": 20})
        ctx = _ctx(start=_dt(hour=18), end=_dt(hour=20), hours=Decimal("2"), base=Decimal("120"))
        assert s.applies(rule, ctx) is False

    def test_compute(self):
        s = MinDurationStrategy()
        rule = _rule({"min_hours": 3, "discount_pct": 20})
        ctx = _ctx(start=_dt(hour=18), end=_dt(hour=22), hours=Decimal("4"), base=Decimal("240"))
        adj = s.compute(rule, ctx, Decimal("240"))
        assert adj == Decimal("-48.00")

    def test_validate_rejects_negative_min_hours(self):
        with pytest.raises(ValidationError):
            MinDurationStrategy.validate_params({"min_hours": 0, "discount_pct": 20})


# ---------------------------------------------------------------------------
# bracket_rate
# ---------------------------------------------------------------------------


class TestBracketRate:
    def test_applies_always(self):
        s = BracketRateStrategy()
        rule = _rule({"brackets": [{"max_hours": None, "rate": "30"}]})
        ctx = _ctx(start=_dt(), end=_dt(hour=22), hours=Decimal("2"), base=Decimal("120"))
        assert s.applies(rule, ctx) is True

    def test_compute_two_brackets(self):
        # 4 hours, brackets: first 2hr @ 50, rest @ 30. Expected total: 100 + 60 = 160.
        s = BracketRateStrategy()
        rule = _rule(
            {"brackets": [{"max_hours": 2, "rate": "50"}, {"max_hours": None, "rate": "30"}]}
        )
        ctx = _ctx(start=_dt(hour=18), end=_dt(hour=22), hours=Decimal("4"), base=Decimal("240"))
        adj = s.compute(rule, ctx, Decimal("240"))
        # desired 160 - running 240 = -80
        assert adj == Decimal("-80")

    def test_compute_single_bracket(self):
        s = BracketRateStrategy()
        rule = _rule({"brackets": [{"max_hours": None, "rate": "40"}]})
        ctx = _ctx(start=_dt(hour=18), end=_dt(hour=20), hours=Decimal("2"), base=Decimal("120"))
        adj = s.compute(rule, ctx, Decimal("120"))
        # desired 80 - running 120 = -40
        assert adj == Decimal("-40")

    def test_compute_fraction_first_bracket(self):
        # Only 1 hour fits in the first bracket (max_hours: 2).
        s = BracketRateStrategy()
        rule = _rule(
            {"brackets": [{"max_hours": 2, "rate": "50"}, {"max_hours": None, "rate": "30"}]}
        )
        ctx = _ctx(start=_dt(hour=18), end=_dt(hour=19), hours=Decimal("1"), base=Decimal("60"))
        adj = s.compute(rule, ctx, Decimal("60"))
        # desired 50 - running 60 = -10
        assert adj == Decimal("-10")

    def test_validate_rejects_empty_brackets(self):
        with pytest.raises(ValidationError):
            BracketRateStrategy.validate_params({"brackets": []})

    def test_validate_rejects_bad_rate(self):
        with pytest.raises(ValidationError):
            BracketRateStrategy.validate_params({"brackets": [{"max_hours": 2, "rate": "free"}]})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_all_five_keys_present(self):
        assert set(RULE_REGISTRY) == {
            "peak_hours",
            "day_of_week",
            "member_tier",
            "min_duration",
            "bracket_rate",
        }

    def test_each_value_is_callable_strategy(self):
        for key, strategy in RULE_REGISTRY.items():
            assert hasattr(strategy, "applies"), f"{key} missing applies()"
            assert hasattr(strategy, "compute"), f"{key} missing compute()"
            assert hasattr(strategy, "validate_params"), f"{key} missing validate_params()"
            assert hasattr(strategy, "params_schema"), f"{key} missing params_schema()"
