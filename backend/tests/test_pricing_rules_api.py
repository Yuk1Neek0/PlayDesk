"""
Tests for /api/admin/pricing-rules/ — task 177 admin CRUD.

Covers happy-path CRUD + 400 on bad params + 404 cross-store isolation.
"""

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
def store_a(db):
    from core.models import Store

    return Store.objects.create(name="Pricing Store A", timezone="UTC")


@pytest.fixture()
def store_b(db):
    from core.models import Store

    return Store.objects.create(name="Pricing Store B", timezone="UTC")


class TestPricingRulesAPI:
    def test_list_empty(self, api_client, store_a):
        resp = api_client.get("/api/admin/pricing-rules/", HTTP_X_PD_STORE_SLUG=store_a.slug)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json() == []

    def test_create_peak_hours(self, api_client, store_a):
        body = {
            "name": "Friday peak",
            "rule_type": "peak_hours",
            "priority": 10,
            "stackable": True,
            "params": {
                "days": ["fri"],
                "start_hour": 20,
                "end_hour": 24,
                "adjustment_pct": 20,
            },
        }
        resp = api_client.post(
            "/api/admin/pricing-rules/", body, format="json", HTTP_X_PD_STORE_SLUG=store_a.slug
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        payload = resp.json()
        assert payload["name"] == "Friday peak"
        assert payload["rule_type"] == "peak_hours"
        assert payload["params"]["adjustment_pct"] == 20

    def test_create_bad_params_400(self, api_client, store_a):
        body = {
            "name": "Bad rule",
            "rule_type": "peak_hours",
            "priority": 10,
            "stackable": True,
            "params": {
                # missing start_hour
                "days": ["fri"],
                "end_hour": 24,
                "adjustment_pct": 20,
            },
        }
        resp = api_client.post(
            "/api/admin/pricing-rules/", body, format="json", HTTP_X_PD_STORE_SLUG=store_a.slug
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "params" in resp.json()

    def test_patch_priority(self, api_client, store_a):
        from pricing.models import PricingRule

        rule = PricingRule.objects.create(
            store=store_a,
            name="Rule",
            rule_type="min_duration",
            priority=100,
            params={"min_hours": 3, "discount_pct": 10},
        )
        resp = api_client.patch(
            f"/api/admin/pricing-rules/{rule.id}/",
            {"priority": 5},
            format="json",
            HTTP_X_PD_STORE_SLUG=store_a.slug,
        )
        assert resp.status_code == status.HTTP_200_OK
        rule.refresh_from_db()
        assert rule.priority == 5

    def test_delete(self, api_client, store_a):
        from pricing.models import PricingRule

        rule = PricingRule.objects.create(
            store=store_a,
            name="Rule",
            rule_type="min_duration",
            priority=100,
            params={"min_hours": 3, "discount_pct": 10},
        )
        resp = api_client.delete(
            f"/api/admin/pricing-rules/{rule.id}/",
            HTTP_X_PD_STORE_SLUG=store_a.slug,
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not PricingRule.objects.filter(pk=rule.id).exists()

    def test_cross_store_404(self, api_client, store_a, store_b):
        # Create a rule on store A
        from pricing.models import PricingRule

        rule = PricingRule.objects.create(
            store=store_a,
            name="A's rule",
            rule_type="min_duration",
            priority=100,
            params={"min_hours": 3, "discount_pct": 10},
        )
        # Access from store B → 404
        resp = api_client.get(
            f"/api/admin/pricing-rules/{rule.id}/",
            HTTP_X_PD_STORE_SLUG=store_b.slug,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_list_is_store_scoped(self, api_client, store_a, store_b):
        from pricing.models import PricingRule

        PricingRule.objects.create(
            store=store_a,
            name="A rule",
            rule_type="min_duration",
            priority=100,
            params={"min_hours": 3, "discount_pct": 10},
        )
        PricingRule.objects.create(
            store=store_b,
            name="B rule",
            rule_type="min_duration",
            priority=100,
            params={"min_hours": 3, "discount_pct": 10},
        )
        resp_a = api_client.get("/api/admin/pricing-rules/", HTTP_X_PD_STORE_SLUG=store_a.slug)
        names_a = {r["name"] for r in resp_a.json()}
        assert names_a == {"A rule"}
