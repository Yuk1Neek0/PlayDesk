"""
Tests for ``POST /api/quote/`` — the public quote endpoint.

Covers the response shape, the no-rules baseline, and the customer-id
flow (tier discount applied when the customer matches a member_tier
rule).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.urls("tests.urls"),
]


@pytest.fixture()
def api_client():
    return APIClient()


@pytest.fixture()
def store(db):
    from core.models import Store

    return Store.objects.create(name="Quote API Store", timezone="UTC")


@pytest.fixture()
def resource(store):
    from core.models import Resource

    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Quote",
        capacity=4,
        price_per_hour=Decimal("60.00"),
    )


def _fri_slot_iso(hours=2):
    start = datetime(2026, 5, 22, 20, 0, tzinfo=UTC)
    end = start + timedelta(hours=hours)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


class TestQuoteAPI:
    def test_no_rules_returns_base(self, api_client, store, resource):
        start_iso, end_iso = _fri_slot_iso()
        resp = api_client.post(
            "/api/quote/",
            {"resource_id": resource.id, "start_at": start_iso, "end_at": end_iso},
            format="json",
            HTTP_X_PD_STORE_SLUG=store.slug,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.content
        body = resp.json()
        assert body["base_amount"] == "120.00"
        assert body["total_amount"] == "120.00"
        assert isinstance(body["line_items"], list) and len(body["line_items"]) == 1
        assert isinstance(body["rule_snapshot"], list)

    def test_customer_id_applies_tier_discount(self, api_client, store, resource):
        from core.memberships import award_points
        from core.models import Customer, RewardTier
        from pricing.models import PricingRule

        gold = RewardTier.objects.create(
            store=store, name="Gold", min_lifetime_points=100, position=1
        )
        cust = Customer.objects.create(store=store, phone="+15550501", name="QC")
        award_points(cust, 150, "backfill", "test")
        PricingRule.objects.create(
            store=store,
            name="Gold 15",
            rule_type="member_tier",
            priority=10,
            stackable=True,
            params={"tier_id": gold.id, "discount_pct": 15},
        )

        start_iso, end_iso = _fri_slot_iso()
        resp = api_client.post(
            "/api/quote/",
            {
                "resource_id": resource.id,
                "start_at": start_iso,
                "end_at": end_iso,
                "customer_id": cust.id,
            },
            format="json",
            HTTP_X_PD_STORE_SLUG=store.slug,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["total_amount"] == "102.00"

    def test_validation_end_before_start(self, api_client, store, resource):
        start_iso, end_iso = _fri_slot_iso()
        resp = api_client.post(
            "/api/quote/",
            {"resource_id": resource.id, "start_at": end_iso, "end_at": start_iso},
            format="json",
            HTTP_X_PD_STORE_SLUG=store.slug,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_resource_not_found(self, api_client, store):
        start_iso, end_iso = _fri_slot_iso()
        resp = api_client.post(
            "/api/quote/",
            {"resource_id": 99999, "start_at": start_iso, "end_at": end_iso},
            format="json",
            HTTP_X_PD_STORE_SLUG=store.slug,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
