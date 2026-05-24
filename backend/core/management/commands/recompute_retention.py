"""Nightly sweeper: recompute Customer.cohort + churn_score.

Pure-deduction over `core.retention`. Iterates with chunk_size=500 so a
10k-customer chain doesn't spike memory. Skips writes when both fields
are unchanged (cohort identical AND churn_score delta < 0.01) — keeps
the cron a no-op when nothing has shifted.

Suggested cron pattern:
    0 3 * * * python manage.py recompute_retention

Options:
    --store SLUG    Scope to a single store.
    --dry-run       Log distribution without writes.
"""

from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Customer
from core.retention import compute_churn_score, compute_cohort

CHUNK_SIZE = 500
# Below this delta a churn_score change is noise — skip the write.
SCORE_EPSILON = 0.01


class Command(BaseCommand):
    help = "Recompute Customer.cohort + churn_score from booking history."

    def add_arguments(self, parser) -> None:  # noqa: D401
        parser.add_argument(
            "--store",
            type=str,
            default=None,
            help="Scope to one store by slug.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Log distribution without writing any rows.",
        )

    def handle(self, *args, **options) -> None:
        store_slug: str | None = options.get("store")
        dry_run: bool = bool(options.get("dry_run"))
        now = timezone.now()

        qs = Customer.objects.all()
        if store_slug:
            qs = qs.filter(store__slug=store_slug)

        # Snapshot the prior cohort distribution for the delta log. Cheap
        # (indexed groupby) and lets us print a useful "+12 / -3" trend
        # line at the end of the run.
        from django.db.models import Count

        prior_counts: Counter[str] = Counter(
            {row["cohort"]: row["count"] for row in qs.values("cohort").annotate(count=Count("id"))}
        )

        new_counts: Counter[str] = Counter()
        writes = 0
        scanned = 0

        for customer in qs.iterator(chunk_size=CHUNK_SIZE):
            scanned += 1
            new_cohort = compute_cohort(customer, now=now)
            new_score = compute_churn_score(customer, now=now)
            new_counts[new_cohort] += 1

            changed = (
                customer.cohort != new_cohort
                or abs(customer.churn_score - new_score) > SCORE_EPSILON
            )
            if not changed:
                continue
            if dry_run:
                continue

            customer.cohort = new_cohort
            customer.churn_score = new_score
            customer.retention_updated_at = now
            customer.save(update_fields=["cohort", "churn_score", "retention_updated_at"])
            writes += 1

        self._log_summary(scanned, writes, prior_counts, new_counts, dry_run)

    def _log_summary(
        self,
        scanned: int,
        writes: int,
        prior: Counter[str],
        new: Counter[str],
        dry_run: bool,
    ) -> None:
        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(f"{prefix}Scanned {scanned} customers, wrote {writes}.")
        # Ordered by "increasing concern" — matches Customer.COHORT_CHOICES.
        order = ["new", "active", "at_risk", "dormant", "lost"]
        parts = []
        for label in order:
            count = new.get(label, 0)
            delta = count - prior.get(label, 0)
            sign = "+" if delta >= 0 else ""
            parts.append(f"{label}: {count} ({sign}{delta})")
        self.stdout.write(f"{prefix}Cohort distribution — {', '.join(parts)}")
