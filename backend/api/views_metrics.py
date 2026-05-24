"""Composite business-metrics endpoint for the /admin dashboard strip.

`GET /api/admin/metrics/business/?days=N` (default 30) returns one fixed-
shape payload sized for one round-trip: six aggregates over Booking,
Customer, OutboundMessage, and QREvent. Each card on the dashboard
maps to one key in the response.

Architecture: every metric is a single `aggregate()` / `count()` — no
Python-side iteration — so the endpoint stays O(query plan) regardless
of table size. A perf regression test seeds 10 000 bookings and asserts
<300ms p95.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core.dates import today_local
from core.models import Booking, Customer, QREvent
from outbound.models import OutboundMessage, OutboundStatus

# QR engagement window is hard-pinned to 7 days per the PRD — the metric
# is only meaningful over a recent slice, and a configurable knob would
# encourage gaming the number.
_QR_WINDOW_DAYS = 7

_DEFAULT_WINDOW_DAYS = 30
_MAX_WINDOW_DAYS = 365


def _parse_days(raw: str | None) -> int:
    try:
        return max(1, min(_MAX_WINDOW_DAYS, int(raw))) if raw is not None else _DEFAULT_WINDOW_DAYS
    except (TypeError, ValueError):
        return _DEFAULT_WINDOW_DAYS


def _count_bookings_on(store, local_date) -> int:
    """Count bookings whose start_time falls within ``local_date`` in the
    store's timezone."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    tz_name = getattr(store, "timezone", "") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    start = datetime.combine(local_date, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return Booking.objects.filter(
        resource__store=store,
        start_time__gte=start,
        start_time__lt=end,
    ).count()


def _trend_pct(today_count: int, yesterday_count: int) -> float | None:
    if yesterday_count == 0:
        return None
    return round((today_count - yesterday_count) / yesterday_count * 100.0, 1)


def _revenue_and_refunds_mtd(store, local_today) -> tuple[str, str]:
    """Decimal-precise revenue + refunds for the current month, store-scoped.

    Returns string-encoded amounts so the JSON payload is exact (no
    float-to-JSON loss). MTD = first of the local-today month.
    """
    from datetime import time as _dtime
    from decimal import Decimal

    from billing.models import Payment, PaymentKind, PaymentRowStatus

    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        tz_name = getattr(store, "timezone", "") or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo("UTC")
    except ImportError:  # pragma: no cover
        tz = None

    month_start_local = local_today.replace(day=1)
    month_start = datetime.combine(month_start_local, _dtime.min, tzinfo=tz)

    revenue = (
        Payment.objects.filter(
            store=store,
            status=PaymentRowStatus.SUCCEEDED,
            kind__in=[PaymentKind.DEPOSIT, PaymentKind.BALANCE],
            created_at__gte=month_start,
        )
        .aggregate(total=Sum("amount"))
        .get("total")
    )
    refunds = (
        Payment.objects.filter(
            store=store,
            status=PaymentRowStatus.SUCCEEDED,
            kind=PaymentKind.REFUND,
            created_at__gte=month_start,
        )
        .aggregate(total=Sum("amount"))
        .get("total")
    )
    return (
        str(Decimal(revenue or 0).quantize(Decimal("0.01"))),
        str(abs(Decimal(refunds or 0)).quantize(Decimal("0.01"))),
    )


def _revenue_cents(store, since) -> int:
    """Sum of completed-booking deposit amounts in the window, in cents.

    Returns 0 when ``Booking`` doesn't expose ``deposit_amount`` (i.e.
    the Stripe slice isn't deployed yet) or when no rows match. Documented
    behaviour in the PRD — never raises.
    """
    if not hasattr(Booking, "deposit_amount"):
        return 0
    agg = (
        Booking.objects.filter(
            resource__store=store,
            status="completed",
            start_time__gte=since,
        )
        .aggregate(total=Sum("deposit_amount"))
        .get("total")
    )
    return int(agg or 0)


class BusinessMetricsView(APIView):
    """`GET /api/admin/metrics/business/?days=N` — one-shot dashboard payload."""

    def get(self, request):
        days = _parse_days(request.query_params.get("days"))
        # ``request.store`` is set by ``CurrentStoreMiddleware``; every
        # aggregate below scopes to it so the dashboard reflects the
        # operator's currently-selected location.
        store = request.store

        # No store yet → zeros for everything. The dashboard renders the
        # cards in their empty state rather than 500-ing.
        if store is None:
            payload = _empty_payload(days)
            return _with_cache(Response(payload))

        local_today = today_local(store)
        local_yesterday = local_today - timedelta(days=1)
        window_since = timezone.now() - timedelta(days=days)
        qr_since = timezone.now() - timedelta(days=_QR_WINDOW_DAYS)
        outbound_since = timezone.now() - timedelta(hours=24)

        # One transaction so the six aggregates see a consistent snapshot.
        with transaction.atomic():
            today_count = _count_bookings_on(store, local_today)
            yesterday_count = _count_bookings_on(store, local_yesterday)

            bookings_window_count = Booking.objects.filter(
                resource__store=store,
                start_time__gte=window_since,
            ).count()

            revenue_cents = _revenue_cents(store, window_since)

            new_customers_count = Customer.objects.filter(
                store=store,
                created_at__gte=window_since,
            ).count()

            outbound_buckets = dict(
                OutboundMessage.objects.filter(
                    customer__store=store,
                    created_at__gte=outbound_since,
                )
                .values_list("status")
                .annotate(n=Count("id"))
            )

            qr_qs = QREvent.objects.filter(store=store, created_at__gte=qr_since)
            qr_buckets = dict(qr_qs.values_list("kind").annotate(n=Count("id")))

        scans = int(qr_buckets.get("scan", 0))
        clicks = int(qr_buckets.get("click", 0))
        engagement_pct = round((clicks / scans * 100.0), 1) if scans else 0.0

        # v9 billing-payments tiles — store-scoped MTD aggregates.
        try:
            revenue_mtd, refunds_mtd = _revenue_and_refunds_mtd(store, local_today)
        except Exception:  # noqa: BLE001
            revenue_mtd, refunds_mtd = "0.00", "0.00"

        payload = {
            "bookings_today": {
                "count": today_count,
                "trend_pct_vs_yesterday": _trend_pct(today_count, yesterday_count),
            },
            "bookings_window": {
                "count": bookings_window_count,
                "window_days": days,
            },
            "revenue_window": {
                "amount_cents": revenue_cents,
                "currency": "CAD",
                "window_days": days,
            },
            "new_customers_window": {
                "count": new_customers_count,
                "window_days": days,
            },
            "outbound_24h": {
                "sent": int(outbound_buckets.get(OutboundStatus.SENT.value, 0)),
                "failed": int(outbound_buckets.get(OutboundStatus.FAILED.value, 0)),
                "queued": int(outbound_buckets.get(OutboundStatus.QUEUED.value, 0)),
            },
            "qr_window": {
                "scans": scans,
                "clicks": clicks,
                "engagement_pct": engagement_pct,
                "window_days": _QR_WINDOW_DAYS,
            },
            "revenue_mtd": {
                "amount": revenue_mtd,
                "currency": store.currency,
            },
            "refunds_mtd": {
                "amount": refunds_mtd,
                "currency": store.currency,
            },
        }
        return _with_cache(Response(payload))


def _empty_payload(days: int) -> dict:
    return {
        "bookings_today": {"count": 0, "trend_pct_vs_yesterday": None},
        "bookings_window": {"count": 0, "window_days": days},
        "revenue_window": {"amount_cents": 0, "currency": "CAD", "window_days": days},
        "new_customers_window": {"count": 0, "window_days": days},
        "outbound_24h": {"sent": 0, "failed": 0, "queued": 0},
        "qr_window": {
            "scans": 0,
            "clicks": 0,
            "engagement_pct": 0.0,
            "window_days": _QR_WINDOW_DAYS,
        },
        "revenue_mtd": {"amount": "0.00", "currency": "USD"},
        "refunds_mtd": {"amount": "0.00", "currency": "USD"},
    }


def _with_cache(response: Response) -> Response:
    # Mild caching: the dashboard polls every 60s; absorbs accidental
    # refreshes without trading much freshness.
    response["Cache-Control"] = "private, max-age=30"
    return response
