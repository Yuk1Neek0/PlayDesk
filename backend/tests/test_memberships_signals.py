"""Tests for the earn-signal wiring — booking completion + QR click hook."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.models import (
    Booking,
    BookingSource,
    BookingStatus,
    Customer,
    PointTransaction,
    QRAction,
    QRActionKind,
    Resource,
    Store,
)


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Earn Store", timezone="UTC", business_hours={})


@pytest.fixture()
def resource(store):
    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5",
        capacity=4,
        price_per_hour="40.00",
        metadata={},
    )


@pytest.fixture()
def customer(store):
    return Customer.objects.create(store=store, phone="+14165550111", name="Alice")


@pytest.fixture()
def actions(store):
    a = QRAction.objects.create(
        store=store,
        kind=QRActionKind.REVIEW,
        label="Review",
        target_url="https://example.com/review",
        position=0,
        reward_points=20,
    )
    a_free = QRAction.objects.create(
        store=store,
        kind=QRActionKind.WIFI,
        label="WiFi",
        target_url="https://example.com/wifi",
        position=1,
        reward_points=0,
    )
    return a, a_free


def _make_booking(resource, customer, **overrides):
    base = datetime(2026, 11, 1, 18, tzinfo=UTC)
    kwargs = dict(
        resource=resource,
        customer=customer,
        customer_name=customer.name if customer else "Anon",
        customer_phone=customer.phone if customer else "+14165550000",
        start_time=base + timedelta(hours=overrides.pop("hour_offset", 0)),
        end_time=base + timedelta(hours=overrides.pop("hour_offset_end", 1)),
        status=BookingStatus.CONFIRMED,
        source=BookingSource.MANUAL,
    )
    kwargs.update(overrides)
    return Booking.objects.create(**kwargs)


# ---------------------------------------------------------------------------
# Booking completion signal
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_booking_completion_awards_points(resource, customer):
    booking = _make_booking(resource, customer)
    assert PointTransaction.objects.filter(customer=customer).count() == 0

    booking.status = BookingStatus.COMPLETED
    booking.save()

    rows = list(PointTransaction.objects.filter(customer=customer))
    assert len(rows) == 1
    assert rows[0].delta == 10  # default points_per_booking
    assert rows[0].source == "booking"
    assert rows[0].reference == str(booking.pk)


@pytest.mark.django_db
def test_booking_resave_while_completed_does_not_duplicate(resource, customer):
    booking = _make_booking(resource, customer)
    booking.status = BookingStatus.COMPLETED
    booking.save()
    booking.save()  # touch
    booking.save()
    assert PointTransaction.objects.filter(customer=customer, source="booking").count() == 1


@pytest.mark.django_db
def test_booking_without_customer_is_noop(resource, customer):
    # Create a booking with a customer first (so signal can be reached), then
    # null its customer_id and resave with status=completed.
    booking = _make_booking(resource, customer)
    booking.customer = None
    booking.status = BookingStatus.COMPLETED
    booking.save()
    assert PointTransaction.objects.count() == 0


@pytest.mark.django_db
def test_booking_points_use_store_config(resource, customer, store):
    store.points_per_booking = 25
    store.save()
    booking = _make_booking(resource, customer)
    booking.status = BookingStatus.COMPLETED
    booking.save()
    pt = PointTransaction.objects.get(customer=customer, source="booking")
    assert pt.delta == 25


@pytest.mark.django_db
def test_booking_zero_points_per_booking_writes_nothing(resource, customer, store):
    store.points_per_booking = 0
    store.save()
    booking = _make_booking(resource, customer)
    booking.status = BookingStatus.COMPLETED
    booking.save()
    assert PointTransaction.objects.filter(customer=customer).count() == 0


# ---------------------------------------------------------------------------
# QR click earn hook
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_qr_click_identified_awards_points(actions, customer, client, store):
    a_review, _a_wifi = actions
    client.cookies["pd_customer"] = str(customer.pk)
    resp = client.post(
        "/api/qr/event/",
        {"slug": store.slug, "kind": "click", "action_id": a_review.id},
        content_type="application/json",
    )
    assert resp.status_code == 201
    pt = PointTransaction.objects.get(customer=customer, source="qr_click")
    assert pt.delta == 20


@pytest.mark.django_db
def test_qr_click_anonymous_no_points(actions, client, store):
    a_review, _a_wifi = actions
    resp = client.post(
        "/api/qr/event/",
        {"slug": store.slug, "kind": "click", "action_id": a_review.id},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert PointTransaction.objects.count() == 0


@pytest.mark.django_db
def test_qr_click_zero_reward_points_writes_nothing(actions, customer, client, store):
    _a_review, a_wifi = actions
    client.cookies["pd_customer"] = str(customer.pk)
    resp = client.post(
        "/api/qr/event/",
        {"slug": store.slug, "kind": "click", "action_id": a_wifi.id},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert PointTransaction.objects.filter(customer=customer).count() == 0


@pytest.mark.django_db
def test_qr_scan_does_not_award_points(actions, customer, client, store):
    client.cookies["pd_customer"] = str(customer.pk)
    resp = client.post(
        "/api/qr/event/",
        {"slug": store.slug, "kind": "scan"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert PointTransaction.objects.filter(customer=customer).count() == 0
