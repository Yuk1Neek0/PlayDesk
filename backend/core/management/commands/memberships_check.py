"""Assert SUM(delta) == latest.balance_after for every customer.

Exit 0 on a clean ledger, exit 1 if any customer's denormalised
``balance_after`` disagrees with the aggregate. Drift means the
single-write-path invariant has been violated somewhere — investigate
before shipping.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import Customer, PointTransaction


class Command(BaseCommand):
    help = "Assert SUM(delta) == latest.balance_after for every customer."

    def handle(self, *args, **options) -> None:
        bad: list[tuple[int, int, int]] = []
        for customer in Customer.objects.all().only("id"):
            agg = PointTransaction.objects.filter(customer_id=customer.id).aggregate(
                s=Sum("delta")
            )["s"]
            total = int(agg or 0)
            latest = (
                PointTransaction.objects.filter(customer_id=customer.id)
                .order_by("-created_at", "-id")
                .first()
            )
            balance = int(latest.balance_after) if latest else 0
            if total != balance:
                bad.append((customer.id, total, balance))

        if bad:
            for customer_id, total, balance in bad:
                self.stderr.write(
                    f"DRIFT customer={customer_id} sum={total} balance_after={balance}"
                )
            self.stderr.write(f"FAIL: {len(bad)} customer(s) with drift")
            raise SystemExit(1)

        self.stdout.write("OK: ledger consistent")
