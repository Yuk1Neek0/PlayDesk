"""
Booking-create wires compute_quote + freezes onto the row + 409 on
``expected_total_amount`` mismatch.

Covers:
  * No rules → total_amount = price_per_hour * hours.
  * peak_hours rule → total_amount reflects the surcharge.
  * matching expected_total_amount → 201.
  * mismatching expected_total_amount → 409 with new_quote payload.
  * omitted expected_total_amount → 201 (backwards-compat).
  * rule_snapshot JSON-serialises and round-trips.
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

    return Store.objects.create(
        name="BookingQuote Store",
        timezone="UTC",
        business_hours={"fri": {"open": "10:00", "close": "23:59"}},
    )


@pytest.fixture()
def resource(store):
    from core.models import Resource

    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 BC",
        capacity=4,
        price_per_hour=Decimal("60.00"),
    )


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _body(resource, *, hours=2, start_hour=20, **extra):
    start = datetime(2026, 5, 22, start_hour, 0, tzinfo=UTC)  # Friday
    body = {
        "resource_id": resource.id,
        "customer_name": "Booker",
        "customer_phone": "+14165550110",
        "start_time": _iso(start),
        "end_time": _iso(start + timedelta(hours=hours)),
        "source": "manual",
    }
    body.update(extra)
    return body


class TestBookingCreateQuote:
    def test_no_rules_total_equals_base(self, api_client, store, resource):
        resp = api_client.post(
            "/api/bookings/", _body(resource), format="json", HTTP_X_PD_STORE_SLUG=store.slug
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        # base 60 * 2 = 120.00
        assert resp.json()["total_amount"] == "120.00"

    def test_peak_hours_rule_applies(self, api_client, store, resource):
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
        resp = api_client.post(
            "/api/bookings/", _body(resource), format="json", HTTP_X_PD_STORE_SLUG=store.slug
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        assert resp.json()["total_amount"] == "144.00"

    def test_expected_total_matching_returns_201(self, api_client, store, resource):
        body = _body(resource, expected_total_amount="120.00")
        resp = api_client.post(
            "/api/bookings/", body, format="json", HTTP_X_PD_STORE_SLUG=store.slug
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.content

    def test_expected_total_mismatch_returns_409_with_new_quote(self, api_client, store, resource):
        # Client thought 120; meanwhile a peak rule was added. Should 409 + new_quote.
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
        body = _body(resource, expected_total_amount="120.00")
        resp = api_client.post(
            "/api/bookings/", body, format="json", HTTP_X_PD_STORE_SLUG=store.slug
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        payload = resp.json()
        assert payload["error"] == "quote_changed"
        assert payload["new_quote"]["total_amount"] == "144.00"

    def test_omitted_expected_total_returns_201(self, api_client, store, resource):
        # Legacy client doesn't send expected_total_amount.
        resp = api_client.post(
            "/api/bookings/", _body(resource), format="json", HTTP_X_PD_STORE_SLUG=store.slug
        )
        assert resp.status_code == status.HTTP_201_CREATED

    def test_rule_snapshot_round_trips(self, api_client, store, resource):
        from pricing.models import PricingRule

        rule = PricingRule.objects.create(
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
        resp = api_client.post(
            "/api/bookings/", _body(resource), format="json", HTTP_X_PD_STORE_SLUG=store.slug
        )
        assert resp.status_code == status.HTTP_201_CREATED
        snap = resp.json()["rule_snapshot"]
        assert isinstance(snap, list) and len(snap) == 2
        assert snap[0]["label"] == "Base" and snap[0]["amount"] == "120.00"
        assert snap[1]["label"] == "Friday peak"
        assert snap[1]["rule_id"] == rule.id
