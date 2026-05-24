"""
Engine tests — the ``compute_quote`` pipeline end-to-end.

Verifies:
  * Zero rules → base only.
  * Single peak_hours surcharge applies.
  * Member-tier discount applies.
  * Stackable peak + tier both apply.
  * Non-stackable peak + stackable tier → both apply (tier is stackable).
  * Two non-stackable rules → only the first one fires.
  * Negative total is floored at 0.
  * Bracket-rate math overrides the base.
  * 50 rules + 1 booking < 50ms (perf assertion).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter

import pytest

pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(db):
    from core.models import Store

    return Store.objects.create(name="Engine Test Store", timezone="UTC")


@pytest.fixture()
def resource(store):
    from core.models import Resource

    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Engine",
        capacity=4,
        price_per_hour=Decimal("60.00"),
    )


def _fri_slot(hours=2):
    # 2026-05-22 is a Friday; 20:00–22:00 UTC by default.
    start = datetime(2026, 5, 22, 20, 0, tzinfo=UTC)
    return start, start + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEngine:
    def test_zero_rules_returns_base(self, resource):
        from pricing.engine import compute_quote

        start, end = _fri_slot(hours=2)
        q = compute_quote(resource, start, end, customer=None)
        assert q.base_amount == Decimal("120.00")
        assert q.total_amount == Decimal("120.00")
        assert len(q.line_items) == 1
        assert q.line_items[0].label == "Base"

    def test_single_peak_hours_surcharge(self, resource, store):
        from pricing.engine import compute_quote
        from pricing.models import PricingRule

        PricingRule.objects.create(
            store=store,
            name="Friday peak",
            rule_type="peak_hours",
            priority=10,
            stackable=True,
            params={
                "days": ["fri"],
                "start_hour": 20,
                "end_hour": 24,
                "adjustment_pct": 20,
            },
        )
        start, end = _fri_slot(hours=2)
        q = compute_quote(resource, start, end, customer=None)
        assert q.total_amount == Decimal("144.00")
        # Base + peak line items
        assert [li.label for li in q.line_items] == ["Base", "Friday peak"]

    def test_member_tier_discount(self, resource, store):
        from core.memberships import award_points
        from core.models import Customer, RewardTier
        from pricing.engine import compute_quote
        from pricing.models import PricingRule

        gold = RewardTier.objects.create(
            store=store, name="Gold", min_lifetime_points=100, position=1
        )
        customer = Customer.objects.create(store=store, phone="+15550101", name="Alice")
        award_points(customer, 150, "backfill", "test")

        PricingRule.objects.create(
            store=store,
            name="Gold discount",
            rule_type="member_tier",
            priority=20,
            stackable=True,
            params={"tier_id": gold.id, "discount_pct": 15},
        )
        start, end = _fri_slot(hours=2)
        q = compute_quote(resource, start, end, customer=customer)
        # 120 - 15% = 102.00
        assert q.total_amount == Decimal("102.00")

    def test_stackable_peak_and_tier(self, resource, store):
        from core.memberships import award_points
        from core.models import Customer, RewardTier
        from pricing.engine import compute_quote
        from pricing.models import PricingRule

        gold = RewardTier.objects.create(
            store=store, name="Gold", min_lifetime_points=100, position=1
        )
        customer = Customer.objects.create(store=store, phone="+15550102", name="Bob")
        award_points(customer, 200, "backfill", "test")

        PricingRule.objects.create(
            store=store,
            name="Peak",
            rule_type="peak_hours",
            priority=10,
            stackable=True,
            params={
                "days": ["fri"],
                "start_hour": 20,
                "end_hour": 24,
                "adjustment_pct": 20,
            },
        )
        PricingRule.objects.create(
            store=store,
            name="Gold",
            rule_type="member_tier",
            priority=20,
            stackable=True,
            params={"tier_id": gold.id, "discount_pct": 15},
        )
        start, end = _fri_slot(hours=2)
        q = compute_quote(resource, start, end, customer=customer)
        # 120 + 20% = 144 -> 144 - 15% = 122.40
        assert q.total_amount == Decimal("122.40")

    def test_non_stackable_peak_does_not_block_stackable_tier(self, resource, store):
        from core.memberships import award_points
        from core.models import Customer, RewardTier
        from pricing.engine import compute_quote
        from pricing.models import PricingRule

        gold = RewardTier.objects.create(
            store=store, name="Gold", min_lifetime_points=100, position=1
        )
        customer = Customer.objects.create(store=store, phone="+15550103", name="Cara")
        award_points(customer, 200, "backfill", "test")

        PricingRule.objects.create(
            store=store,
            name="Peak NS",
            rule_type="peak_hours",
            priority=10,
            stackable=False,
            params={
                "days": ["fri"],
                "start_hour": 20,
                "end_hour": 24,
                "adjustment_pct": 20,
            },
        )
        PricingRule.objects.create(
            store=store,
            name="Gold",
            rule_type="member_tier",
            priority=20,
            stackable=True,  # stackable, must still fire
            params={"tier_id": gold.id, "discount_pct": 15},
        )
        start, end = _fri_slot(hours=2)
        q = compute_quote(resource, start, end, customer=customer)
        # peak (NS) fires first, tier (stackable) still fires → 122.40
        assert q.total_amount == Decimal("122.40")

    def test_two_non_stackable_only_first_fires(self, resource, store):
        from pricing.engine import compute_quote
        from pricing.models import PricingRule

        # Both apply to Friday 20:00–22:00 — only the first (priority 10)
        # should fire because both are non-stackable.
        PricingRule.objects.create(
            store=store,
            name="Cheap Friday",
            rule_type="day_of_week",
            priority=10,
            stackable=False,
            params={"days": ["fri"], "discount_pct": 30},
        )
        PricingRule.objects.create(
            store=store,
            name="Friday peak",
            rule_type="peak_hours",
            priority=20,
            stackable=False,
            params={
                "days": ["fri"],
                "start_hour": 20,
                "end_hour": 24,
                "adjustment_pct": 50,
            },
        )
        start, end = _fri_slot(hours=2)
        q = compute_quote(resource, start, end, customer=None)
        # 120 - 30% = 84 (peak surcharge skipped)
        assert q.total_amount == Decimal("84.00")
        assert [li.label for li in q.line_items] == ["Base", "Cheap Friday"]

    def test_negative_total_floored_at_zero(self, resource, store):
        from pricing.engine import compute_quote
        from pricing.models import PricingRule

        # Discount pct > 100 isn't allowed by member_tier validation, but
        # day_of_week with flat_rate=0 is, and a single rule could over-
        # discount. Test the floor with a manually-injected rule.
        PricingRule.objects.create(
            store=store,
            name="Free Friday",
            rule_type="day_of_week",
            priority=10,
            stackable=True,
            params={"days": ["fri"], "flat_rate": "0"},
        )
        start, end = _fri_slot(hours=2)
        q = compute_quote(resource, start, end, customer=None)
        # Override to 0; floor keeps it non-negative.
        assert q.total_amount == Decimal("0.00")

    def test_bracket_rate(self, resource, store):
        from pricing.engine import compute_quote
        from pricing.models import PricingRule

        # 4-hour booking; brackets [2hr @ 50, rest @ 30] = 100 + 60 = 160
        PricingRule.objects.create(
            store=store,
            name="Bracket",
            rule_type="bracket_rate",
            priority=10,
            stackable=True,
            params={
                "brackets": [{"max_hours": 2, "rate": "50"}, {"max_hours": None, "rate": "30"}]
            },
        )
        start = datetime(2026, 5, 22, 18, 0, tzinfo=UTC)
        end = start + timedelta(hours=4)
        q = compute_quote(resource, start, end, customer=None)
        assert q.total_amount == Decimal("160.00")

    def test_perf_50_rules_under_50ms(self, resource, store):
        from pricing.engine import compute_quote
        from pricing.models import PricingRule

        # Half non-stackable peak rules that don't fire (Saturday only),
        # half stackable member-tier rules that don't fire (no customer
        # tier). The engine still loops + filters all 50.
        for i in range(25):
            PricingRule.objects.create(
                store=store,
                name=f"Sat peak #{i}",
                rule_type="peak_hours",
                priority=100 + i,
                stackable=False,
                params={
                    "days": ["sat"],
                    "start_hour": 20,
                    "end_hour": 24,
                    "adjustment_pct": 10,
                },
            )
            PricingRule.objects.create(
                store=store,
                name=f"Tier rule #{i}",
                rule_type="member_tier",
                priority=200 + i,
                stackable=True,
                params={"tier_id": 99999, "discount_pct": 5},
            )

        start, end = _fri_slot(hours=2)

        # Warm-up call (JIT, query-cache warmup).
        compute_quote(resource, start, end, customer=None)

        t0 = perf_counter()
        for _ in range(5):
            compute_quote(resource, start, end, customer=None)
        elapsed_ms = (perf_counter() - t0) * 1000 / 5
        assert elapsed_ms < 50, f"compute_quote averaged {elapsed_ms:.2f}ms (target <50ms)"
