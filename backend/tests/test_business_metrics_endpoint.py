"""Tests for the composite business-metrics endpoint.

Covers per-aggregate correctness, the trend math edge cases, the cache
header, and a perf-regression test seeded with 10 000 bookings + 100 000
QR events that asserts the endpoint stays under 300ms p95.
"""

from __future__ import annotations

import time as _time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Booking,
    BookingSource,
    BookingStatus,
    Customer,
    QREvent,
    QREventKind,
    Resource,
    Store,
)
from outbound.models import OutboundMessage, OutboundStatus

URL = "/api/admin/metrics/business/"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(db):
    return Store.objects.create(
        name="Metrics Store", slug="metrics-store", timezone="UTC", business_hours={}
    )


@pytest.fixture()
def resource(store):
    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 #1",
        capacity=4,
        price_per_hour="40.00",
        metadata={},
    )


def _make_booking(
    resource,
    *,
    start,
    customer=None,
    status: str = BookingStatus.CONFIRMED,
    bump_minutes: int = 0,
):
    """Create a booking, offsetting by `bump_minutes` to dodge the
    no-overlap exclusion constraint when several bookings share a slot."""
    start = start + timedelta(minutes=bump_minutes)
    end = start + timedelta(minutes=30)
    return Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=(customer.name if customer else "Walk-in"),
        customer_phone=(customer.phone if customer else "+10000000000"),
        start_time=start,
        end_time=end,
        status=status,
        source=BookingSource.MANUAL,
    )


# ---------------------------------------------------------------------------
# Empty DB
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_empty_db_returns_all_zero(store, client):
    resp = client.get(URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["bookings_today"] == {"count": 0, "trend_pct_vs_yesterday": None}
    assert body["bookings_window"]["count"] == 0
    assert body["bookings_window"]["window_days"] == 30
    assert body["revenue_window"]["amount_cents"] == 0
    assert body["revenue_window"]["currency"] == "CAD"
    assert body["new_customers_window"]["count"] == 0
    assert body["outbound_24h"] == {"sent": 0, "failed": 0, "queued": 0}
    assert body["qr_window"]["scans"] == 0
    assert body["qr_window"]["clicks"] == 0
    assert body["qr_window"]["engagement_pct"] == 0.0
    assert body["qr_window"]["window_days"] == 7


@pytest.mark.django_db
def test_cache_header_present(store, client):
    resp = client.get(URL)
    assert resp.headers.get("Cache-Control") == "private, max-age=30"


# ---------------------------------------------------------------------------
# Bookings — today vs window
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bookings_today_vs_window(store, resource, client):
    now = timezone.now()
    # Today: 2 bookings (different start minutes to avoid overlap).
    _make_booking(resource, start=now.replace(hour=10, minute=0))
    _make_booking(resource, start=now.replace(hour=12, minute=0))
    # 5 days ago: in window but not today.
    _make_booking(resource, start=now - timedelta(days=5), bump_minutes=0)
    # 60 days ago: outside the default 30-day window.
    _make_booking(resource, start=now - timedelta(days=60), bump_minutes=0)

    resp = client.get(URL)
    body = resp.json()
    assert body["bookings_today"]["count"] == 2
    # In-window bookings: 2 today + 1 five-days-ago = 3.
    assert body["bookings_window"]["count"] == 3


@pytest.mark.django_db
def test_bookings_today_trend_positive(store, resource, client):
    # 2 bookings today, 1 yesterday → trend = +100.0.
    now = timezone.now()
    _make_booking(resource, start=now.replace(hour=10, minute=0))
    _make_booking(resource, start=now.replace(hour=12, minute=0))
    yesterday = now - timedelta(days=1)
    _make_booking(resource, start=yesterday.replace(hour=10, minute=0))

    body = client.get(URL).json()
    assert body["bookings_today"]["count"] == 2
    assert body["bookings_today"]["trend_pct_vs_yesterday"] == 100.0


@pytest.mark.django_db
def test_bookings_today_trend_null_when_yesterday_zero(store, resource, client):
    # 1 booking today, 0 yesterday → null (divide-by-zero avoidance).
    now = timezone.now()
    _make_booking(resource, start=now.replace(hour=10, minute=0))

    body = client.get(URL).json()
    assert body["bookings_today"]["count"] == 1
    assert body["bookings_today"]["trend_pct_vs_yesterday"] is None


# ---------------------------------------------------------------------------
# Revenue — Stripe-unconfigured (no deposit_amount field) returns 0
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_revenue_zero_when_no_deposit_amount(store, resource, client):
    # `Booking.deposit_amount` doesn't exist in main yet — confirm we
    # gracefully return 0 instead of raising.
    now = timezone.now()
    _make_booking(resource, start=now, status="completed")
    body = client.get(URL).json()
    assert body["revenue_window"]["amount_cents"] == 0
    assert body["revenue_window"]["currency"] == "CAD"


# ---------------------------------------------------------------------------
# New customers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_new_customers_within_window(store, client):
    # Two fresh customers should count.
    Customer.objects.create(store=store, phone="+14165550100", name="Alice")
    Customer.objects.create(store=store, phone="+14165550101", name="Bob")
    # An older customer outside the window must not. created_at is
    # auto_now_add so we patch the row in place.
    old = Customer.objects.create(store=store, phone="+14165550102", name="Old")
    Customer.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=60))

    body = client.get(URL).json()
    assert body["new_customers_window"]["count"] == 2


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_outbound_24h_counts_by_status(store, client):
    customer = Customer.objects.create(store=store, phone="+14165550111", name="A")
    for status in (
        OutboundStatus.SENT,
        OutboundStatus.SENT,
        OutboundStatus.FAILED,
        OutboundStatus.QUEUED,
    ):
        OutboundMessage.objects.create(
            customer=customer,
            template_key="confirmation",
            body="hi",
            status=status,
        )
    # One stale row (older than 24h) — must not count.
    stale = OutboundMessage.objects.create(
        customer=customer,
        template_key="confirmation",
        body="old",
        status=OutboundStatus.SENT,
    )
    OutboundMessage.objects.filter(pk=stale.pk).update(
        created_at=timezone.now() - timedelta(hours=48)
    )

    body = client.get(URL).json()
    assert body["outbound_24h"] == {"sent": 2, "failed": 1, "queued": 1}


# ---------------------------------------------------------------------------
# QR engagement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_qr_engagement_math(store, client):
    # 10 scans + 3 clicks → engagement = 30.0%.
    for _ in range(10):
        QREvent.objects.create(store=store, kind=QREventKind.SCAN)
    for _ in range(3):
        QREvent.objects.create(store=store, kind=QREventKind.CLICK)
    body = client.get(URL).json()
    assert body["qr_window"]["scans"] == 10
    assert body["qr_window"]["clicks"] == 3
    assert body["qr_window"]["engagement_pct"] == 30.0


@pytest.mark.django_db
def test_qr_window_pinned_to_seven_days(store, client):
    # Event 10 days ago must not count in qr_window (hard-pinned 7d).
    stale = QREvent.objects.create(store=store, kind=QREventKind.SCAN)
    QREvent.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(days=10))
    body = client.get(URL).json()
    assert body["qr_window"]["scans"] == 0


# ---------------------------------------------------------------------------
# URL routing
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reverse_resolves(store, client):
    # Sanity: the named route resolves to the same URL we're hitting.
    assert reverse("api:admin-business-metrics") == URL


# ---------------------------------------------------------------------------
# Perf regression — 10k bookings + 100k QR events
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _perf_seeded(django_db_setup, django_db_blocker):
    """Module-scoped seed: 10 000 bookings + 100 000 QREvents in one store.

    Bulk-created to skip the outbound booking signals (each create would
    otherwise fan out into the outbound queue, which is irrelevant here
    and would dominate seed time).
    """
    with django_db_blocker.unblock():
        store = Store.objects.create(
            name="Perf Store", slug="perf-store", timezone="UTC", business_hours={}
        )
        # One resource per booking lets us bulk-create without the
        # exclusion constraint complaining about overlap.
        resource = Resource.objects.create(
            store=store,
            type="console",
            name="Perf PS5",
            capacity=4,
            price_per_hour="40.00",
            metadata={},
        )

        # 10 000 bookings spread out over 30 days so each booking gets
        # its own slot. Stagger by minute to keep them non-overlapping
        # for the same resource.
        now = timezone.now()
        bookings = []
        for i in range(10_000):
            start = now - timedelta(days=29) + timedelta(minutes=i * 3)
            bookings.append(
                Booking(
                    resource=resource,
                    customer_name=f"Perf {i}",
                    customer_phone="+10000000000",
                    start_time=start,
                    end_time=start + timedelta(minutes=2),
                    status=BookingStatus.CONFIRMED,
                    source=BookingSource.MANUAL,
                )
            )
        Booking.objects.bulk_create(bookings, batch_size=2000)

        # 100 000 QR events.
        qr_events = [QREvent(store=store, kind="scan") for _ in range(80_000)]
        qr_events += [QREvent(store=store, kind="click") for _ in range(20_000)]
        QREvent.objects.bulk_create(qr_events, batch_size=5000)

    yield store

    with django_db_blocker.unblock():
        # Module-scoped teardown — the test DB is reused across the
        # session but we don't want this seed bleeding into other modules.
        Booking.objects.filter(resource__store=store).delete()
        QREvent.objects.filter(store=store).delete()
        Resource.objects.filter(store=store).delete()
        store.delete()


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("_perf_seeded")
def test_business_metrics_perf_under_300ms(client):
    # Warm the connection + query plan with one call we don't time.
    client.get(URL)

    samples = []
    for _ in range(10):
        t0 = _time.perf_counter()
        resp = client.get(URL)
        samples.append(_time.perf_counter() - t0)
        assert resp.status_code == 200

    samples.sort()
    # p95 over 10 samples == 95th-percentile == samples[9] (the slowest).
    p95 = samples[-1]
    assert p95 < 0.300, f"endpoint p95={p95 * 1000:.1f}ms exceeds 300ms budget"


# ---------------------------------------------------------------------------
# Store-local "today" — bookings_today uses store TZ, not UTC
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bookings_today_uses_store_local_tz(client, resource):
    """At a UTC moment where store-local ("America/Toronto") is the
    previous day, a booking placed during that store-local day must
    count towards `bookings_today`."""
    store = resource.store
    store.timezone = "America/Toronto"
    store.save()

    # Real UTC moment we'll pretend is "now": 03:00 UTC on 2026-06-02.
    # In America/Toronto that's 23:00 EDT on 2026-06-01.
    fake_now = datetime(2026, 6, 2, 3, 0, tzinfo=UTC)
    # Booking lives at 20:00 EDT on 2026-06-01 == 00:00 UTC on 2026-06-02.
    booking_start = datetime(2026, 6, 2, 0, 0, tzinfo=UTC)
    _make_booking(resource, start=booking_start)

    # Patch both `core.dates.timezone.now` (for today_local) and the
    # view's own `timezone.now` references so window math uses the
    # same fake clock.
    with (
        patch("core.dates.timezone.now", return_value=fake_now),
        patch("api.views_metrics.timezone.now", return_value=fake_now),
    ):
        body = client.get(URL).json()
    assert body["bookings_today"]["count"] == 1
