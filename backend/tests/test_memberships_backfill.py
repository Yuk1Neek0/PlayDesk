"""Tests for the points backfill migration (0010_backfill_points).

Exercise the migration's forward/reverse functions directly so we can
test on a populated dataset without bouncing the full migration chain.
"""

from __future__ import annotations

from importlib import import_module

import pytest

from core.memberships import award_points
from core.models import Customer, PointTransaction, Store

_migration = import_module("core.migrations.0010_backfill_points")


def _seed_backfill() -> None:
    _migration._seed_backfill(None, None)


def _reverse_backfill() -> None:
    _migration._reverse_backfill(None, None)


@pytest.fixture()
def store(db):
    return Store.objects.create(
        name="Backfill Store", timezone="UTC", business_hours={}, points_per_booking=10
    )


@pytest.fixture()
def second_store(db):
    return Store.objects.create(
        name="Backfill Store 2", timezone="UTC", business_hours={}, points_per_booking=25
    )


@pytest.mark.django_db
def test_backfill_empty_db_is_noop():
    _seed_backfill()
    assert PointTransaction.objects.count() == 0


@pytest.mark.django_db
def test_backfill_seeds_each_customer_with_visits(store):
    a = Customer.objects.create(store=store, phone="+14165550111", total_visits=3)
    b = Customer.objects.create(store=store, phone="+14165550222", total_visits=5)
    Customer.objects.create(store=store, phone="+14165550333", total_visits=0)

    _seed_backfill()

    pt_a = PointTransaction.objects.get(customer=a)
    pt_b = PointTransaction.objects.get(customer=b)
    assert pt_a.delta == 30
    assert pt_a.source == "backfill"
    assert pt_a.reference == "backfill-v4"
    assert pt_a.balance_after == 30
    assert pt_b.delta == 50
    # Customer with zero visits gets no row.
    assert PointTransaction.objects.count() == 2


@pytest.mark.django_db
def test_backfill_respects_per_store_points(store, second_store):
    a = Customer.objects.create(store=store, phone="+14165550111", total_visits=2)
    b = Customer.objects.create(store=second_store, phone="+14165550111", total_visits=2)
    _seed_backfill()
    assert PointTransaction.objects.get(customer=a).delta == 20
    assert PointTransaction.objects.get(customer=b).delta == 50


@pytest.mark.django_db
def test_backfill_idempotent(store):
    c = Customer.objects.create(store=store, phone="+14165550111", total_visits=3)
    _seed_backfill()
    _seed_backfill()
    _seed_backfill()
    assert PointTransaction.objects.filter(customer=c).count() == 1


@pytest.mark.django_db
def test_backfill_skips_customer_with_existing_transaction(store):
    c = Customer.objects.create(store=store, phone="+14165550111", total_visits=3)
    award_points(c, 99, "adjustment", "pre-existing")
    _seed_backfill()
    # No backfill row added; only the pre-existing one remains.
    assert PointTransaction.objects.filter(customer=c).count() == 1
    assert not PointTransaction.objects.filter(customer=c, source="backfill").exists()


@pytest.mark.django_db
def test_reverse_only_removes_backfill_rows(store):
    c = Customer.objects.create(store=store, phone="+14165550111", total_visits=3)
    _seed_backfill()
    award_points(c, 5, "adjustment", "manual top-up")
    assert PointTransaction.objects.filter(customer=c).count() == 2

    _reverse_backfill()

    remaining = list(PointTransaction.objects.filter(customer=c))
    assert len(remaining) == 1
    assert remaining[0].source == "adjustment"
