"""Tests for the memberships helper module + management command."""

from __future__ import annotations

import threading

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection

from core.memberships import (
    award_points,
    current_balance,
    lifetime_points_earned,
    next_tier_for,
    tier_for,
)
from core.models import Customer, PointTransaction, RewardTier, Store


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Mem Store", timezone="UTC", business_hours={})


@pytest.fixture()
def customer(store):
    return Customer.objects.create(store=store, phone="+14165550111", name="Alice")


@pytest.fixture()
def tiers(store):
    """Three tiers on `store`: Bronze 0, Silver 100, Gold 500."""
    bronze = RewardTier.objects.create(
        store=store, name="Bronze", min_lifetime_points=0, perks_text="", position=0
    )
    silver = RewardTier.objects.create(
        store=store, name="Silver", min_lifetime_points=100, perks_text="", position=1
    )
    gold = RewardTier.objects.create(
        store=store, name="Gold", min_lifetime_points=500, perks_text="", position=2
    )
    return bronze, silver, gold


# ---------------------------------------------------------------------------
# award_points
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_award_positive_delta_creates_row_and_updates_balance(customer):
    pt = award_points(customer, 10, "booking", "b-1")
    assert pt.delta == 10
    assert pt.balance_after == 10
    assert pt.source == "booking"
    assert pt.reference == "b-1"
    assert current_balance(customer) == 10


@pytest.mark.django_db
def test_award_negative_delta_debits(customer):
    award_points(customer, 30, "booking", "b-1")
    pt = award_points(customer, -10, "redemption", "r-1")
    assert pt.balance_after == 20
    assert current_balance(customer) == 20


@pytest.mark.django_db
def test_award_zero_delta_rejected(customer):
    with pytest.raises(ValueError):
        award_points(customer, 0, "adjustment", "noop")


@pytest.mark.django_db
def test_award_records_author(customer):
    User = get_user_model()
    staff = User.objects.create_user(username="staff", password="x")
    pt = award_points(customer, 5, "adjustment", "manual", author=staff)
    assert pt.author_id == staff.id


@pytest.mark.django_db(transaction=True)
def test_award_concurrent_calls_preserve_invariant(customer):
    """Two threads earning at the same time both succeed and `balance_after`
    matches `SUM(delta)`.
    """
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker(delta: int) -> None:
        try:
            barrier.wait(timeout=5)
            award_points(customer, delta, "booking", f"b-{delta}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    t1 = threading.Thread(target=worker, args=(7,))
    t2 = threading.Thread(target=worker, args=(11,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not errors, errors

    rows = list(PointTransaction.objects.filter(customer=customer).order_by("created_at", "id"))
    assert len(rows) == 2
    total = sum(r.delta for r in rows)
    assert rows[-1].balance_after == total == 18


# ---------------------------------------------------------------------------
# lifetime_points_earned
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_lifetime_excludes_negative_deltas(customer):
    award_points(customer, 50, "booking", "b-1")
    award_points(customer, 30, "booking", "b-2")
    award_points(customer, -20, "redemption", "r-1")
    assert lifetime_points_earned(customer) == 80
    assert current_balance(customer) == 60


# ---------------------------------------------------------------------------
# tier_for — five edge cases per spec
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tier_empty_balance_returns_lowest_or_none(customer, tiers):
    bronze, _silver, _gold = tiers
    # Bronze threshold is 0 — every customer hits it from the start.
    assert tier_for(customer) == bronze


@pytest.mark.django_db
def test_tier_no_tiers_configured_returns_none(customer):
    assert tier_for(customer) is None


@pytest.mark.django_db
def test_tier_no_tiers_below_lowest_returns_none(customer, store):
    RewardTier.objects.create(
        store=store, name="Silver", min_lifetime_points=100, perks_text="", position=0
    )
    # Customer has 0 lifetime — below the only tier's threshold.
    assert tier_for(customer) is None


@pytest.mark.django_db
def test_tier_exact_threshold_selects_that_tier(customer, tiers):
    _bronze, silver, _gold = tiers
    award_points(customer, 100, "booking", "b-1")
    assert tier_for(customer) == silver


@pytest.mark.django_db
def test_tier_between_thresholds(customer, tiers):
    _bronze, silver, _gold = tiers
    award_points(customer, 200, "booking", "b-1")
    assert tier_for(customer) == silver


@pytest.mark.django_db
def test_tier_above_top_returns_top(customer, tiers):
    _bronze, _silver, gold = tiers
    award_points(customer, 10_000, "booking", "b-1")
    assert tier_for(customer) == gold


@pytest.mark.django_db
def test_tier_not_downgraded_by_redemption(customer, tiers):
    _bronze, _silver, gold = tiers
    award_points(customer, 600, "booking", "b-1")
    assert tier_for(customer) == gold
    award_points(customer, -500, "redemption", "r-1")
    # Lifetime earned is still 600, so still Gold even though balance is 100.
    assert tier_for(customer) == gold


@pytest.mark.django_db
def test_next_tier(customer, tiers):
    _bronze, silver, gold = tiers
    assert next_tier_for(customer) == silver
    award_points(customer, 100, "booking", "b-1")
    assert next_tier_for(customer) == gold
    award_points(customer, 500, "booking", "b-2")
    assert next_tier_for(customer) is None


# ---------------------------------------------------------------------------
# memberships_check command
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_memberships_check_passes_on_consistent_data(customer, capsys):
    award_points(customer, 10, "booking", "b-1")
    award_points(customer, 20, "booking", "b-2")
    call_command("memberships_check")
    out = capsys.readouterr().out
    assert "OK" in out


@pytest.mark.django_db
def test_memberships_check_fails_on_drift(customer, capsys):
    award_points(customer, 10, "booking", "b-1")
    # Force drift by writing directly, bypassing award_points.
    PointTransaction.objects.create(
        customer=customer,
        delta=5,
        source="adjustment",
        reference="hand-rolled",
        balance_after=999,  # wrong — should be 15
    )
    with pytest.raises(SystemExit) as exc_info:
        call_command("memberships_check")
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "DRIFT" in err
