"""Tests for v11c retention-scoring schema additions on Customer.

The fields themselves are computed nightly by `recompute_retention`
(task #211); this file only asserts the data layer additions made in
task #210 — defaults, indexes, serializer surface.
"""

from __future__ import annotations

import pytest
from django.db import connection

from api.serializers import CustomerDetailSerializer, CustomerSummarySerializer
from core.models import Customer, Store


@pytest.fixture()
def store(db):
    return Store.objects.create(name="RetentionStore", timezone="UTC", business_hours={})


@pytest.mark.django_db(transaction=True)
def test_create_applies_field_defaults(store):
    c = Customer.objects.create(store=store, phone="+15550001111", name="Defaults")
    assert c.cohort == "new"
    assert c.churn_score == 0.0
    assert c.retention_updated_at is None


@pytest.mark.django_db(transaction=True)
def test_summary_serializer_exposes_retention_fields(store):
    c = Customer.objects.create(store=store, phone="+15550002222", name="Surface")
    data = CustomerSummarySerializer(c).data
    assert data["cohort"] == "new"
    assert data["churn_score"] == 0.0
    assert data["retention_updated_at"] is None


@pytest.mark.django_db(transaction=True)
def test_detail_serializer_exposes_retention_fields(store):
    c = Customer.objects.create(store=store, phone="+15550003333", name="DetailSurface")
    data = CustomerDetailSerializer(c).data
    assert {"cohort", "churn_score", "retention_updated_at"} <= set(data.keys())


@pytest.mark.django_db(transaction=True)
def test_named_indexes_exist(store):
    """The migration declares explicit names; confirm Postgres created them.

    Auto-generated names are a known v4 campaigns CI flake source — the
    explicit names in 0019_customer_retention_fields.py protect us.
    """
    constraints = connection.introspection.get_constraints(
        connection.cursor(), Customer._meta.db_table
    )
    names = set(constraints.keys())
    assert "customer_cohort_idx" in names
    assert "customer_churn_score_idx" in names
