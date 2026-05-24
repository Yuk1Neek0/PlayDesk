"""
Pricing engine — the pure ``compute_quote`` function that turns a
``(resource, start_at, end_at, customer)`` tuple into a ``Quote``.

Pure: no DB writes. Reads ``PricingRule`` rows for the resource's store +
the customer's tier (via v4 ``tier_for``). The engine has no knowledge of
any concrete rule type — it loops the active rules in priority order and
delegates to ``RULE_REGISTRY[rule.rule_type]`` for both the ``applies()``
check and the signed adjustment in ``compute()``.

Decimal arithmetic throughout. Final total is floored at 0 and rounded
to 2dp; intermediate math runs at the default Decimal precision so the
rounding doesn't bias multi-rule stacks.

Determinism: same inputs → same output. No ``now()`` reads.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Customer, Resource


@dataclass
class QuoteLineItem:
    """One row in the breakdown the customer sees.

    ``amount`` is signed: negative = discount, positive = surcharge.
    ``rule_id`` is None for the synthetic "Base" line; otherwise it's the
    ``PricingRule.id`` that produced the adjustment.
    """

    label: str
    amount: Decimal
    rule_id: int | None = None

    def to_dict(self) -> dict:
        """JSON-safe dict — Decimals stringified so json.dumps doesn't choke."""
        return {
            "label": self.label,
            "amount": str(self.amount),
            "rule_id": self.rule_id,
        }


@dataclass
class Quote:
    """Result of one ``compute_quote`` call.

    ``rule_snapshot`` is the same content as ``line_items`` but pre-serialised
    so callers (booking-create freeze) can drop it straight into the
    ``Booking.rule_snapshot`` JSONField without re-walking the list.
    """

    base_amount: Decimal
    line_items: list[QuoteLineItem]
    total_amount: Decimal
    rule_snapshot: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "base_amount": str(self.base_amount),
            "line_items": [li.to_dict() for li in self.line_items],
            "total_amount": str(self.total_amount),
            "rule_snapshot": self.rule_snapshot,
        }


def _hours_between(start: datetime, end: datetime) -> Decimal:
    """Compute hours as a 4-dp Decimal without float drift."""
    seconds = int((end - start).total_seconds())
    return (Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.0001"))


def compute_quote(
    resource: Resource,
    start_at: datetime,
    end_at: datetime,
    customer: Customer | None = None,
) -> Quote:
    """Evaluate the store's pricing rules against ``(resource, slot, customer)``.

    Algorithm:
      1. Base = ``resource.price_per_hour * hours`` → first line item.
      2. Resolve ``customer_tier`` via ``core.memberships.tier_for`` (one query).
      3. Load all enabled ``PricingRule`` rows for the store (one query),
         keep those where ``applies_to_resource`` is null or matches.
      4. For each rule in (priority, id) order:
            * Skip if a non-stackable rule already fired and this one is also
              non-stackable.
            * Skip if ``strategy.applies(...)`` is False.
            * Append the signed adjustment from ``strategy.compute(...)`` to
              the running total + line items.
            * Mark the non-stackable flag if applicable.
      5. Floor total at 0 and round to 2dp.

    Performance: < 50ms for a store with 50 rules — single rule query +
    single tier query, all math in Python.
    """
    # Late imports keep ``compute_quote`` free to be called from contexts where
    # the Django app registry hasn't loaded yet (e.g. tests).
    from pricing.models import PricingRule
    from pricing.strategies import RULE_REGISTRY, QuoteContext

    hours = _hours_between(start_at, end_at)
    base_amount = (resource.price_per_hour * hours).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    line_items: list[QuoteLineItem] = [
        QuoteLineItem(label="Base", amount=base_amount, rule_id=None)
    ]
    running_total: Decimal = base_amount

    # Resolve the customer's tier (None for anonymous bookings).
    customer_tier = None
    if customer is not None:
        try:
            from core.memberships import tier_for

            customer_tier = tier_for(customer)
        except Exception:  # noqa: BLE001 — tier lookup is best-effort
            customer_tier = None

    ctx = QuoteContext(
        resource=resource,
        start_at=start_at,
        end_at=end_at,
        customer=customer,
        customer_tier=customer_tier,
        hours=hours,
        base_amount=base_amount,
    )

    # Single query for the rules. select_related on the resource FK so the
    # ``applies_to_resource`` filter doesn't trigger N+1.
    rules = list(
        PricingRule.objects.filter(store_id=resource.store_id, enabled=True)
        .select_related("applies_to_resource")
        .order_by("priority", "id")
    )

    non_stackable_fired = False
    for rule in rules:
        # Resource scope: null = all resources in store; non-null must match.
        if rule.applies_to_resource_id is not None and rule.applies_to_resource_id != resource.id:
            continue
        # Non-stackable gate: once a non-stackable rule fires, subsequent
        # non-stackable rules are skipped. Stackable rules always evaluate.
        if non_stackable_fired and not rule.stackable:
            continue
        strategy = RULE_REGISTRY.get(rule.rule_type)
        if strategy is None:
            # Unknown rule_type — defensive skip; admin form validates on
            # write but never trust the DB.
            continue
        if not strategy.applies(rule, ctx):
            continue
        adjustment = strategy.compute(rule, ctx, running_total)
        line_items.append(QuoteLineItem(label=rule.name, amount=adjustment, rule_id=rule.id))
        running_total = running_total + adjustment
        if not rule.stackable:
            non_stackable_fired = True

    # Floor at zero AFTER summing all adjustments; per-rule floors would
    # bias multi-discount stacks.
    if running_total < 0:
        running_total = Decimal("0")
    total_amount = running_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return Quote(
        base_amount=base_amount,
        line_items=line_items,
        total_amount=total_amount,
        rule_snapshot=[li.to_dict() for li in line_items],
    )


__all__ = ["Quote", "QuoteLineItem", "compute_quote"]


# Avoid an unused-symbol lint when only the dataclass `asdict` helper is
# wanted by external callers.
_ = asdict
