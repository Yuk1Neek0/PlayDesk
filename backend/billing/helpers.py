"""Pure helpers for deposit math + refund-matrix lookup.

No Stripe calls, no DB writes — just functions over Decimal/JSON. Easy
to unit-test exhaustively; called by the booking-create endpoint and
the cancel-refund flow.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.utils import timezone

_TWOPLACES = Decimal("0.01")


def _quantize(d: Decimal) -> Decimal:
    return d.quantize(_TWOPLACES, rounding=ROUND_HALF_UP)


def _resolve_deposit_policy(store, resource) -> tuple[str, Decimal]:
    """Pick `(mode, value)` for the booking — resource override wins.

    A non-null `Resource.deposit_override_mode` always trumps the
    store default (even "none" — letting a premium resource opt out).
    """
    override_mode = getattr(resource, "deposit_override_mode", None)
    if override_mode:
        return (
            override_mode,
            Decimal(resource.deposit_override_value or 0),
        )
    return (
        store.deposit_mode or "none",
        Decimal(store.deposit_value or 0),
    )


def calc_deposit(store, resource, total_amount) -> Decimal:
    """Compute deposit owed for a booking, capped at the total.

    Modes:
      - none       → 0.00
      - percentage → total * value / 100
      - fixed      → min(total, value)
    Always quantized to 2dp.
    """
    total = Decimal(total_amount)
    if total <= 0:
        return Decimal("0.00")

    mode, value = _resolve_deposit_policy(store, resource)
    if mode == "none":
        return Decimal("0.00")
    if mode == "percentage":
        # Cap at total in case of an out-of-range percentage.
        pct = max(Decimal("0"), min(value, Decimal("100")))
        return _quantize(min(total, total * pct / Decimal("100")))
    if mode == "fixed":
        return _quantize(min(total, max(Decimal("0"), value)))
    # Unknown mode — fail closed: no deposit.
    return Decimal("0.00")


def _sorted_matrix(matrix: list[dict]) -> list[dict]:
    """Top-down sort by `min_hours` desc so the first match wins."""
    rows = [r for r in (matrix or []) if isinstance(r, dict) and "min_hours" in r]
    return sorted(rows, key=lambda r: r["min_hours"], reverse=True)


def find_refund_pct(matrix: list[dict], lead_hours: float) -> int:
    """Return the matching `refund_pct` for `lead_hours` (0 if no match)."""
    for row in _sorted_matrix(matrix):
        if lead_hours >= row["min_hours"]:
            return int(row.get("refund_pct", 0))
    return 0


def calc_refund_amount(store, booking, now=None) -> Decimal:
    """Compute the refund owed when `booking` cancels at `now`.

    Reads `Store.refund_matrix`; finds the first row whose `min_hours`
    lead time has been met; applies that percentage to the captured
    `deposit_amount` (only deposits refund automatically — balance
    refunds are staff-discretion in v9).
    """
    if booking.deposit_amount is None or Decimal(booking.deposit_amount) <= 0:
        return Decimal("0.00")
    if now is None:
        now = timezone.now()
    lead_hours = (booking.start_time - now).total_seconds() / 3600.0
    pct = find_refund_pct(store.refund_matrix or [], lead_hours)
    if pct <= 0:
        return Decimal("0.00")
    refund = Decimal(booking.deposit_amount) * Decimal(pct) / Decimal("100")
    return _quantize(refund)


def validate_refund_matrix(matrix: Any) -> list[dict]:
    """Schema-validate a matrix payload; raise ValueError on bad shape.

    Used by the admin settings save endpoint. The matrix is stored as
    raw JSON; we want to fail at save time rather than runtime, with a
    message the admin can act on.
    """
    if not isinstance(matrix, list):
        raise ValueError("refund_matrix must be a JSON array")
    cleaned = []
    for i, row in enumerate(matrix):
        if not isinstance(row, dict):
            raise ValueError(f"row {i}: must be an object")
        if "min_hours" not in row or "refund_pct" not in row:
            raise ValueError(f"row {i}: missing min_hours / refund_pct")
        try:
            mh = int(row["min_hours"])
            pct = int(row["refund_pct"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"row {i}: min_hours/refund_pct must be integers") from exc
        if mh < 0 or pct < 0 or pct > 100:
            raise ValueError(f"row {i}: out-of-range value")
        cleaned.append({"min_hours": mh, "refund_pct": pct})
    return cleaned
