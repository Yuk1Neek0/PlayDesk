"""Tests for v11c retention-scoring: pure deduction + nightly sweeper."""

from __future__ import annotations

import time
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Customer, Store
from core.retention import compute_churn_score, compute_cohort

NOW = timezone.now()


@pytest.fixture()
def store(db):
    return Store.objects.create(name="RetStore", timezone="UTC", business_hours={})


@pytest.fixture()
def other_store(db):
    return Store.objects.create(name="OtherStore", timezone="UTC", business_hours={})


def _make_customer(store, *, phone, visits=0, last_visit_ago_days=None, created_ago_days=0):
    """Build a saved Customer with last_visit_at + created_at tuned for the test.

    `auto_now_add` makes `created_at` un-settable at .create() time, so
    we patch it via a follow-up `update(...)` when the test needs a
    specific age.
    """
    last_visit_at = (
        NOW - timedelta(days=last_visit_ago_days) if last_visit_ago_days is not None else None
    )
    c = Customer.objects.create(
        store=store,
        phone=phone,
        name=f"Cust {phone[-4:]}",
        total_visits=visits,
        last_visit_at=last_visit_at,
    )
    if created_ago_days:
        Customer.objects.filter(pk=c.pk).update(created_at=NOW - timedelta(days=created_ago_days))
        c.refresh_from_db()
    return c


# ---------------------------------------------------------------------------
# compute_cohort — every threshold
# ---------------------------------------------------------------------------


def test_cohort_new_when_no_visits_and_fresh(store):
    c = _make_customer(store, phone="+15550000001", visits=0, created_ago_days=2)
    assert compute_cohort(c, now=NOW) == "new"


def test_cohort_lost_when_no_last_visit_after_7_days(store):
    # 0 visits but signed up 30 days ago — the "new" grace expired.
    c = _make_customer(store, phone="+15550000002", visits=0, created_ago_days=30)
    assert compute_cohort(c, now=NOW) == "lost"


def test_cohort_active_when_recent_visit(store):
    c = _make_customer(store, phone="+15550000003", visits=3, last_visit_ago_days=5)
    assert compute_cohort(c, now=NOW) == "active"


def test_cohort_at_risk_between_30_and_60(store):
    c = _make_customer(store, phone="+15550000004", visits=3, last_visit_ago_days=45)
    assert compute_cohort(c, now=NOW) == "at_risk"


def test_cohort_dormant_between_60_and_90(store):
    c = _make_customer(store, phone="+15550000005", visits=3, last_visit_ago_days=75)
    assert compute_cohort(c, now=NOW) == "dormant"


def test_cohort_lost_over_90(store):
    c = _make_customer(store, phone="+15550000006", visits=3, last_visit_ago_days=120)
    assert compute_cohort(c, now=NOW) == "lost"


# ---------------------------------------------------------------------------
# compute_churn_score — math
# ---------------------------------------------------------------------------


def test_churn_score_zero_when_just_visited(store):
    c = _make_customer(store, phone="+15550100001", visits=2, last_visit_ago_days=0)
    assert compute_churn_score(c, now=NOW) == 0.0


def test_churn_score_one_when_no_last_visit(store):
    c = _make_customer(store, phone="+15550100002", visits=0)
    assert compute_churn_score(c, now=NOW) == 1.0


def test_churn_score_baseline_at_45_days(store):
    # 45 / 90 = 0.5, visits<5 so no multiplier.
    c = _make_customer(store, phone="+15550100003", visits=2, last_visit_ago_days=45)
    assert compute_churn_score(c, now=NOW) == pytest.approx(0.5, abs=0.01)


def test_churn_score_multiplier_for_high_frequency(store):
    # 30 days, 10 visits → baseline 0.333 * min(2.0, 10/10=1.0) = 0.333.
    c = _make_customer(store, phone="+15550100004", visits=10, last_visit_ago_days=30)
    assert compute_churn_score(c, now=NOW) == pytest.approx(0.333, abs=0.01)


def test_churn_score_multiplier_caps_at_2x(store):
    # 100 visits, 30 days dark → baseline 0.333 * min(2.0, 10.0) = 0.666.
    c = _make_customer(store, phone="+15550100005", visits=100, last_visit_ago_days=30)
    assert compute_churn_score(c, now=NOW) == pytest.approx(0.666, abs=0.01)


def test_churn_score_clamped_at_one(store):
    # 200 days dark, 100 visits → would overflow; clamp.
    c = _make_customer(store, phone="+15550100006", visits=100, last_visit_ago_days=200)
    assert compute_churn_score(c, now=NOW) == 1.0


# ---------------------------------------------------------------------------
# recompute_retention management command
# ---------------------------------------------------------------------------


def _run_command(*args) -> str:
    out = StringIO()
    call_command("recompute_retention", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db(transaction=True)
def test_command_assigns_correct_cohorts(store):
    cohorts = {
        "new": _make_customer(store, phone="+15550200001", visits=0, created_ago_days=2),
        "active": _make_customer(store, phone="+15550200002", visits=3, last_visit_ago_days=5),
        "at_risk": _make_customer(store, phone="+15550200003", visits=3, last_visit_ago_days=45),
        "dormant": _make_customer(store, phone="+15550200004", visits=3, last_visit_ago_days=75),
        "lost": _make_customer(store, phone="+15550200005", visits=3, last_visit_ago_days=120),
    }

    _run_command()

    for expected_cohort, c in cohorts.items():
        c.refresh_from_db()
        assert c.cohort == expected_cohort, f"{c.phone}: got {c.cohort}, want {expected_cohort}"
        assert c.retention_updated_at is not None


@pytest.mark.django_db(transaction=True)
def test_dry_run_does_not_write(store):
    c = _make_customer(store, phone="+15550300001", visits=3, last_visit_ago_days=75)
    assert c.cohort == "new"  # default before sweeper

    output = _run_command("--dry-run")

    c.refresh_from_db()
    assert c.cohort == "new"  # unchanged
    assert c.retention_updated_at is None
    assert "dry-run" in output
    assert "dormant: 1" in output


@pytest.mark.django_db(transaction=True)
def test_store_filter_only_touches_target_store(store, other_store):
    target = _make_customer(store, phone="+15550400001", visits=3, last_visit_ago_days=45)
    other = _make_customer(other_store, phone="+15550400002", visits=3, last_visit_ago_days=45)

    _run_command("--store", store.slug)

    target.refresh_from_db()
    other.refresh_from_db()
    assert target.cohort == "at_risk"
    assert other.cohort == "new"  # untouched
    assert other.retention_updated_at is None


@pytest.mark.django_db(transaction=True)
def test_command_is_idempotent(store):
    _make_customer(store, phone="+15550500001", visits=3, last_visit_ago_days=45)
    _run_command()
    output_2nd = _run_command()
    # Second run should report 0 writes — nothing changed.
    assert "wrote 0" in output_2nd


@pytest.mark.django_db(transaction=True)
def test_command_logs_distribution_with_delta(store):
    # Seed three across two cohorts; first run sets them.
    _make_customer(store, phone="+15550600001", visits=3, last_visit_ago_days=5)
    _make_customer(store, phone="+15550600002", visits=3, last_visit_ago_days=45)
    _make_customer(store, phone="+15550600003", visits=3, last_visit_ago_days=45)

    output = _run_command()
    assert "active: 1" in output
    assert "at_risk: 2" in output
    # The first run's delta is calculated against the pre-run default
    # cohort ("new") — so the line carries explicit signs.
    assert "(+" in output


@pytest.mark.django_db(transaction=True)
def test_performance_under_1000_customers(store):
    """Sweeper must process 1000 customers in well under 5 seconds."""
    customers = [
        Customer(
            store=store,
            phone=f"+1555099{i:04d}",
            name=f"Perf {i}",
            total_visits=3,
            last_visit_at=NOW - timedelta(days=10 + (i % 80)),
        )
        for i in range(1000)
    ]
    Customer.objects.bulk_create(customers)

    started = time.perf_counter()
    _run_command()
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"sweeper took {elapsed:.2f}s (limit 5.0s)"
    # All seeded customers wrote a retention timestamp.
    assert Customer.objects.filter(retention_updated_at__isnull=False).count() >= 1000
