"""Tests for the segment DSL evaluator (`customers_for`).

Includes the cross-store invariant — proved with two stores and the
broadest possible filter on store A.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from django.utils import timezone

from campaigns.models import Segment
from campaigns.segments import customers_for
from core.models import Customer, Store


@pytest.fixture()
def store_a(db):
    return Store.objects.create(name="Store A", timezone="UTC", business_hours={})


@pytest.fixture()
def store_b(db):
    return Store.objects.create(name="Store B", timezone="UTC", business_hours={})


@pytest.fixture()
def populated(store_a, store_b):
    now = timezone.now()
    a_vip = Customer.objects.create(
        store=store_a,
        phone="+14165550001",
        name="A-VIP",
        tags=["vip", "regular"],
        total_visits=10,
        last_visit_at=now - timedelta(days=5),
        locale_pref="en",
    )
    a_lapsed = Customer.objects.create(
        store=store_a,
        phone="+14165550002",
        name="A-Lapsed",
        tags=["vip"],
        total_visits=3,
        last_visit_at=now - timedelta(days=200),
        locale_pref="zh",
    )
    a_new = Customer.objects.create(
        store=store_a,
        phone="+14165550003",
        name="A-New",
        tags=[],
        total_visits=0,
        last_visit_at=None,
        locale_pref="en",
    )
    b_vip = Customer.objects.create(
        store=store_b,
        phone="+14165550004",
        name="B-VIP",
        tags=["vip"],
        total_visits=20,
        last_visit_at=now,
        locale_pref="en",
    )
    return {"a_vip": a_vip, "a_lapsed": a_lapsed, "a_new": a_new, "b_vip": b_vip}


# ---------------------------------------------------------------------------
# Store scoping
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_empty_filter_returns_all_store_customers(store_a, populated):
    seg = Segment.objects.create(store=store_a, name="All", filter={})
    pks = set(customers_for(seg).values_list("pk", flat=True))
    assert pks == {populated["a_vip"].pk, populated["a_lapsed"].pk, populated["a_new"].pk}


@pytest.mark.django_db
def test_cross_store_invariant(store_a, store_b, populated):
    """The broadest possible filter on store A must never return any of
    store B's customers."""
    seg = Segment.objects.create(store=store_a, name="All A", filter={})
    pks = set(customers_for(seg).values_list("pk", flat=True))
    assert populated["b_vip"].pk not in pks


# ---------------------------------------------------------------------------
# Single-key filters
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tags_include_single(store_a, populated):
    seg = Segment.objects.create(store=store_a, name="VIPs", filter={"tags_include": ["vip"]})
    pks = set(customers_for(seg).values_list("pk", flat=True))
    assert pks == {populated["a_vip"].pk, populated["a_lapsed"].pk}


@pytest.mark.django_db
def test_tags_include_requires_all_listed_tags(store_a, populated):
    seg = Segment.objects.create(
        store=store_a, name="VIP+Reg", filter={"tags_include": ["vip", "regular"]}
    )
    pks = set(customers_for(seg).values_list("pk", flat=True))
    assert pks == {populated["a_vip"].pk}


@pytest.mark.django_db
def test_min_total_visits(store_a, populated):
    seg = Segment.objects.create(store=store_a, name="5+ visits", filter={"min_total_visits": 5})
    pks = set(customers_for(seg).values_list("pk", flat=True))
    assert pks == {populated["a_vip"].pk}


@pytest.mark.django_db
def test_min_total_visits_zero_matches_all(store_a, populated):
    seg = Segment.objects.create(store=store_a, name="0+ visits", filter={"min_total_visits": 0})
    pks = set(customers_for(seg).values_list("pk", flat=True))
    assert pks == {populated["a_vip"].pk, populated["a_lapsed"].pk, populated["a_new"].pk}


@pytest.mark.django_db
def test_last_visit_within_days(store_a, populated):
    seg = Segment.objects.create(
        store=store_a, name="Active 30d", filter={"last_visit_within_days": 30}
    )
    pks = set(customers_for(seg).values_list("pk", flat=True))
    assert pks == {populated["a_vip"].pk}


@pytest.mark.django_db
def test_last_visit_within_days_zero_matches_only_today(store_a):
    now = timezone.now()
    today_visitor = Customer.objects.create(
        store=store_a,
        phone="+1010101",
        name="Today",
        last_visit_at=now,
    )
    Customer.objects.create(
        store=store_a,
        phone="+1010102",
        name="Yesterday",
        last_visit_at=now - timedelta(days=1, hours=1),
    )
    seg = Segment.objects.create(
        store=store_a, name="Today only", filter={"last_visit_within_days": 0}
    )
    pks = set(customers_for(seg).values_list("pk", flat=True))
    assert pks == {today_visitor.pk}


@pytest.mark.django_db
def test_locale_pref(store_a, populated):
    seg = Segment.objects.create(store=store_a, name="ZH", filter={"locale_pref": "zh"})
    pks = set(customers_for(seg).values_list("pk", flat=True))
    assert pks == {populated["a_lapsed"].pk}


# ---------------------------------------------------------------------------
# Combined filters
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_combined_keys_and_together(store_a, populated):
    seg = Segment.objects.create(
        store=store_a,
        name="Active VIPs",
        filter={
            "tags_include": ["vip"],
            "min_total_visits": 5,
            "last_visit_within_days": 60,
            "locale_pref": "en",
        },
    )
    pks = set(customers_for(seg).values_list("pk", flat=True))
    assert pks == {populated["a_vip"].pk}


# ---------------------------------------------------------------------------
# Unknown keys
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_unknown_key_logs_warning_and_does_not_raise(store_a, populated, caplog):
    seg = Segment.objects.create(store=store_a, name="Future key", filter={"future_key": "ignored"})
    with caplog.at_level(logging.WARNING, logger="campaigns.segments"):
        pks = set(customers_for(seg).values_list("pk", flat=True))
    assert pks == {populated["a_vip"].pk, populated["a_lapsed"].pk, populated["a_new"].pk}
    assert any("unknown segment key: future_key" in r.message for r in caplog.records)
