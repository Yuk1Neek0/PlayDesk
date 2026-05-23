"""
Memberships — the single ledger-write helper plus the tier resolver.

Every earn / spend / adjustment / backfill in the system funnels through
``award_points``. It is the *only* code path that writes to
``PointTransaction``. Concurrency-safe via ``select_for_update`` on the
customer row, so two simultaneous earn events for the same customer
serialise and ``balance_after`` never disagrees with ``SUM(delta)``.

``tier_for`` is a pure function of ``lifetime_points_earned`` (sum of
positive deltas), so a redemption never downgrades a customer's tier.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Sum

from .models import Customer, PointTransaction, RewardTier


def lifetime_points_earned(customer: Customer) -> int:
    """Sum of all positive deltas for the customer (earn-only total)."""
    total = PointTransaction.objects.filter(customer=customer, delta__gt=0).aggregate(
        s=Sum("delta")
    )["s"]
    return int(total or 0)


def current_balance(customer: Customer) -> int:
    """Current balance — ``balance_after`` of the latest row, or 0."""
    latest = (
        PointTransaction.objects.filter(customer=customer).order_by("-created_at", "-id").first()
    )
    return int(latest.balance_after) if latest else 0


def award_points(
    customer: Customer,
    delta: int,
    source: str,
    reference: str = "",
    author=None,
) -> PointTransaction:
    """Append one row to the ledger and return it.

    The only code path that writes ``PointTransaction``. Locks the
    customer row with ``select_for_update`` so concurrent calls on the
    same customer serialise and ``balance_after`` stays consistent with
    ``SUM(delta)``.

    Raises ``ValueError`` on ``delta == 0`` — a zero-delta row would
    pollute the ledger without changing anything.
    """
    if delta == 0:
        raise ValueError("award_points: delta must be non-zero")

    with transaction.atomic():
        # Lock the customer row so concurrent writes serialise.
        Customer.objects.select_for_update().filter(pk=customer.pk).first()
        latest = (
            PointTransaction.objects.filter(customer=customer)
            .order_by("-created_at", "-id")
            .first()
        )
        prior = int(latest.balance_after) if latest else 0
        return PointTransaction.objects.create(
            customer=customer,
            delta=int(delta),
            source=source,
            reference=reference,
            author=author,
            balance_after=prior + int(delta),
        )


def tier_for(customer: Customer) -> RewardTier | None:
    """Return the tier the customer currently sits in, or ``None``.

    Pure function of ``lifetime_points_earned``: the highest tier whose
    ``min_lifetime_points`` is ``<=`` the lifetime total. Returns
    ``None`` when the customer is below the lowest tier or no tiers are
    configured for the store.
    """
    lifetime = lifetime_points_earned(customer)
    tiers = list(
        RewardTier.objects.filter(store_id=customer.store_id).order_by("-min_lifetime_points")
    )
    for tier in tiers:
        if lifetime >= tier.min_lifetime_points:
            return tier
    return None


def next_tier_for(customer: Customer) -> RewardTier | None:
    """Return the lowest tier the customer has not yet reached, or ``None``."""
    lifetime = lifetime_points_earned(customer)
    return (
        RewardTier.objects.filter(store_id=customer.store_id, min_lifetime_points__gt=lifetime)
        .order_by("min_lifetime_points")
        .first()
    )
