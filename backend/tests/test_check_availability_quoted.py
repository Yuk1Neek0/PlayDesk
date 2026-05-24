"""
Verify the v8 ``check_availability`` returns ``quoted_price`` on each
available slot after a peak_hours rule fires.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture()
def store(db):
    from core.models import Store

    return Store.objects.create(name="Quoted Avail Store", timezone="UTC")


@pytest.fixture()
def resource(store):
    from core.models import Resource

    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Avail",
        capacity=4,
        price_per_hour=Decimal("60.00"),
    )


class TestCheckAvailabilityQuoted:
    def test_quoted_price_includes_peak_surcharge(self, store, resource):
        from agent_tools.schemas import CheckAvailabilityInput
        from agent_tools.tools import check_availability
        from pricing.models import PricingRule

        PricingRule.objects.create(
            store=store,
            name="Fri peak",
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

        # 2026-05-22 Friday 20-22 UTC
        inp = CheckAvailabilityInput(
            resource_type="console",
            date="2026-05-22",
            time_range=("20:00", "22:00"),
            party_size=2,
            store_id=store.id,
        )
        out = check_availability(inp)
        assert len(out.available) == 1
        slot = out.available[0]
        # Base 60*2=120 + 20% = 144.00
        assert slot.quoted_price == "144.00"
        assert slot.resource_id == resource.id

    def test_quoted_price_present_without_rules(self, store, resource):
        from agent_tools.schemas import CheckAvailabilityInput
        from agent_tools.tools import check_availability

        # Fri 20-22 UTC, no rules -> base 120.00
        # (UTC == store timezone so the time-of-day used by the engine
        # matches the input window.)
        inp = CheckAvailabilityInput(
            resource_type="console",
            date="2026-05-22",
            time_range=("20:00", "22:00"),
            party_size=2,
            store_id=store.id,
        )
        out = check_availability(inp)
        assert len(out.available) == 1
        assert out.available[0].quoted_price == "120.00"

    def test_get_resource_details_display_text_no_rules(self, store, resource):
        from agent_tools.schemas import GetResourceDetailsInput
        from agent_tools.tools import get_resource_details

        out = get_resource_details(GetResourceDetailsInput(store_id=store.id))
        assert len(out.resources) == 1
        # No discount rule configured for store -> no "from " prefix
        assert out.resources[0].display_price_text == "$60/hr"

    def test_get_resource_details_display_text_with_discount_rule(self, store, resource):
        from agent_tools.schemas import GetResourceDetailsInput
        from agent_tools.tools import get_resource_details
        from pricing.models import PricingRule

        PricingRule.objects.create(
            store=store,
            name="Min duration",
            rule_type="min_duration",
            priority=10,
            stackable=True,
            params={"min_hours": 3, "discount_pct": 20},
        )
        out = get_resource_details(GetResourceDetailsInput(store_id=store.id))
        assert len(out.resources) == 1
        # discount rule present → "from ..." prefix
        assert out.resources[0].display_price_text == "from $60/hr"

    def test_datetime_module_import(self):
        # Sanity check that datetime is importable inside the test module,
        # avoiding an unused-import lint when other tests grow.
        assert datetime(2026, 1, 1, tzinfo=UTC).year == 2026
