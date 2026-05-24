"""Deterministic cohort + churn-score deduction for Customer rows.

Pure functions — no DB queries beyond the customer row's own fields.
Called by the `recompute_retention` management command nightly. Cohort
labels match `Customer.COHORT_CHOICES`; thresholds are tuned for the
game-lounge product (a 30-day gap is "at_risk", 60+ "dormant", 90+
"lost"). Tune in one place when the chain says "your at_risk window is
too aggressive for esports venues".
"""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

# Exposed for the sweeper + tests; keep in sync with Customer.COHORT_CHOICES.
COHORT_NEW = "new"
COHORT_ACTIVE = "active"
COHORT_AT_RISK = "at_risk"
COHORT_DORMANT = "dormant"
COHORT_LOST = "lost"


def compute_cohort(customer, now: datetime | None = None) -> str:
    """Deduce the cohort label for `customer` from its own fields.

    Pure — no DB queries. The order of checks matters: a 0-visit
    just-signed-up customer reads as `new`, not `lost`.
    """
    now = now or timezone.now()
    last = customer.last_visit_at
    created = customer.created_at
    visits = customer.total_visits

    # `created_at` is auto_now_add — for a brand-new in-memory instance
    # that hasn't been saved yet (used in unit tests of compute_cohort
    # directly), fall back to `now` so the "new" rule still triggers.
    if created is None:
        created = now

    if visits == 0 and (now - created).days < 7:
        return COHORT_NEW
    if last is None or (now - last).days > 90:
        return COHORT_LOST
    days_since = (now - last).days
    if days_since > 60:
        return COHORT_DORMANT
    if days_since > 30:
        return COHORT_AT_RISK
    return COHORT_ACTIVE


def compute_churn_score(customer, now: datetime | None = None) -> float:
    """Deduce `churn_score` (0.0 engaged → 1.0 lost) from the row.

    Baseline = `days_since_last_visit / 90`, clamped to [0, 1].
    Frequency adjustment: a customer with many lifetime visits going
    dark for the same duration is more concerning — multiply baseline
    by min(2.0, total_visits / 10) when `total_visits >= 5`. Final
    clamp to [0, 1] so the multiplier can't push past the ceiling.
    """
    now = now or timezone.now()
    last = customer.last_visit_at
    visits = customer.total_visits

    if last is None:
        return 1.0

    days_since = max(0, (now - last).days)
    score = days_since / 90.0

    if visits >= 5:
        multiplier = min(2.0, visits / 10.0)
        score *= multiplier

    return max(0.0, min(1.0, score))
