"""Tests for the v11c cohort filter + counts + bulk-send endpoint."""

from __future__ import annotations

import pytest

from core.models import Customer, Store
from outbound.models import OutboundMessage, OutboundStatus


@pytest.fixture()
def store(db):
    return Store.objects.create(name="CohortStore", timezone="UTC", business_hours={})


@pytest.fixture()
def other_store(db):
    return Store.objects.create(name="OtherCohortStore", timezone="UTC", business_hours={})


@pytest.fixture()
def cohort_seed(store):
    """Two dormant + one active + one dormant-with-opt-out — for filters + bulk-send."""
    return {
        "active": Customer.objects.create(
            store=store, phone="+15550000111", name="Active A", cohort="active"
        ),
        "dormant1": Customer.objects.create(
            store=store, phone="+15550000222", name="Dormant B", cohort="dormant"
        ),
        "dormant2": Customer.objects.create(
            store=store, phone="+15550000333", name="Dormant C", cohort="dormant"
        ),
        "dormant_optout": Customer.objects.create(
            store=store,
            phone="+15550000444",
            name="Dormant D",
            cohort="dormant",
            tags=["sms_opt_out"],
        ),
    }


# ---------------------------------------------------------------------------
# List filter + counts
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_list_returns_cohort_counts(cohort_seed, client):
    resp = client.get("/api/admin/customers/")
    assert resp.status_code == 200
    body = resp.json()
    assert "cohort_counts" in body
    counts = body["cohort_counts"]
    # Every label present, even when zero.
    assert set(counts.keys()) == {"new", "active", "at_risk", "dormant", "lost"}
    assert counts["dormant"] == 3
    assert counts["active"] == 1
    assert counts["new"] == 0


@pytest.mark.django_db(transaction=True)
def test_cohort_filter_narrows_results(cohort_seed, client):
    resp = client.get("/api/admin/customers/?cohort=dormant")
    body = resp.json()
    assert body["count"] == 3
    cohorts = {r["cohort"] for r in body["results"]}
    assert cohorts == {"dormant"}


@pytest.mark.django_db(transaction=True)
def test_unknown_cohort_silently_ignored(cohort_seed, client):
    resp = client.get("/api/admin/customers/?cohort=bogus")
    # Unknown filter value behaves like no filter (matches existing
    # channel/status filter ergonomics on AdminConversationListView).
    assert resp.json()["count"] == 4


# ---------------------------------------------------------------------------
# Bulk-send endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_bulk_send_enqueues_dormant_customers(cohort_seed, client):
    resp = client.post(
        "/api/admin/customers/bulk-send/",
        {"cohort": "dormant", "template_key": "re_engagement_60d"},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["sent"] == 2  # the 2 non-opt-out dormants
    assert body["skipped"] == 1
    assert body["skip_reasons"]["opt_out"] == 1

    queued = OutboundMessage.objects.filter(template_key="re_engagement_60d")
    assert queued.count() == 2
    # Every queued row is for a real customer + carries the rendered body.
    for row in queued:
        assert row.status == OutboundStatus.QUEUED
        assert "first hour" in row.body or "免费" in row.body


@pytest.mark.django_db(transaction=True)
def test_bulk_send_writes_audit_note(cohort_seed, client):
    client.post(
        "/api/admin/customers/bulk-send/",
        {"cohort": "dormant", "template_key": "re_engagement_60d"},
        content_type="application/json",
    )
    # The two non-opted-out dormants each gained one audit note.
    assert cohort_seed["dormant1"].notes.count() == 1
    assert cohort_seed["dormant2"].notes.count() == 1
    # The opted-out one was skipped — no note.
    assert cohort_seed["dormant_optout"].notes.count() == 0
    body = cohort_seed["dormant1"].notes.first().body
    assert "re_engagement_60d" in body and "bulk action" in body


@pytest.mark.django_db(transaction=True)
def test_bulk_send_rejects_unknown_template(cohort_seed, client):
    resp = client.post(
        "/api/admin/customers/bulk-send/",
        {"cohort": "dormant", "template_key": "booking_confirmation"},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert OutboundMessage.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_bulk_send_rejects_unknown_cohort(cohort_seed, client):
    resp = client.post(
        "/api/admin/customers/bulk-send/",
        {"cohort": "bogus", "template_key": "re_engagement_60d"},
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_bulk_send_does_not_cross_store_boundaries(cohort_seed, other_store, client):
    # Add a dormant customer in the OTHER store. The current request
    # is scoped to the seeded `store` via CurrentStoreMiddleware fallback,
    # so this row must NOT receive a message.
    Customer.objects.create(
        store=other_store, phone="+15550008888", name="Other Dormant", cohort="dormant"
    )
    client.post(
        "/api/admin/customers/bulk-send/",
        {"cohort": "dormant", "template_key": "re_engagement_60d"},
        content_type="application/json",
    )
    # OutboundMessage rows have a FK to Customer; check the customer FK
    # to confirm the other-store row never received one.
    other_phones = set(
        OutboundMessage.objects.filter(template_key="re_engagement_60d").values_list(
            "customer__phone", flat=True
        )
    )
    assert "+15550008888" not in other_phones


@pytest.mark.django_db(transaction=True)
def test_re_engagement_template_renders():
    from outbound.templates import render_template

    out = render_template("re_engagement_60d", "en", {"customer_name": "Alice"})
    assert "Alice" in out
    assert "first hour" in out
    zh = render_template("re_engagement_60d", "zh", {"customer_name": "小明"})
    assert "小明" in zh
