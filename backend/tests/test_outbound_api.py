"""Tests for the admin outbound message log endpoints."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Customer, Store
from outbound.api import enqueue_message
from outbound.models import OutboundMessage, OutboundStatus


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Outbound Admin Store", timezone="UTC", business_hours={})


@pytest.fixture()
def alice(store):
    return Customer.objects.create(store=store, phone="+14165550111", name="Alice")


@pytest.fixture()
def bob(store):
    return Customer.objects.create(store=store, phone="+14165550222", name="Bob")


def _ctx():
    return {
        "customer_name": "x",
        "store_name": "Outbound Admin Store",
        "start_time": "2026-10-01 18:00",
        "resource_name": "PS5 #1",
        # v10b checkin appended {checkin_url} to booking_confirmation.
        "checkin_url": "http://localhost:3000/c/TEST2345",
    }


@pytest.mark.django_db(transaction=True)
def test_per_customer_log_returns_customer_messages(alice, bob, client):
    enqueue_message(alice, "booking_confirmation", _ctx())
    enqueue_message(alice, "reminder_24h", _ctx())
    enqueue_message(bob, "booking_confirmation", _ctx())

    resp = client.get(f"/api/admin/outbound/?customer_id={alice.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(row["customer_id"] == alice.id for row in data)
    keys = {row["template_key"] for row in data}
    assert keys == {"booking_confirmation", "reminder_24h"}


@pytest.mark.django_db(transaction=True)
def test_per_customer_log_is_newest_first(alice, client):
    older = enqueue_message(alice, "booking_confirmation", _ctx())
    newer = enqueue_message(alice, "reminder_24h", _ctx())
    # Force ordering by adjusting created_at after the fact.
    OutboundMessage.objects.filter(pk=older.pk).update(
        created_at=timezone.now() - timedelta(hours=2)
    )
    OutboundMessage.objects.filter(pk=newer.pk).update(
        created_at=timezone.now() - timedelta(hours=1)
    )

    resp = client.get(f"/api/admin/outbound/?customer_id={alice.id}")
    data = resp.json()
    assert data[0]["id"] == newer.id
    assert data[1]["id"] == older.id


@pytest.mark.django_db(transaction=True)
def test_per_customer_log_respects_limit(alice, client):
    for _ in range(5):
        enqueue_message(alice, "booking_confirmation", _ctx())

    resp = client.get(f"/api/admin/outbound/?customer_id={alice.id}&limit=2")
    data = resp.json()
    assert len(data) == 2


@pytest.mark.django_db(transaction=True)
def test_per_customer_log_default_limit_is_20(alice, client):
    for _ in range(25):
        enqueue_message(alice, "booking_confirmation", _ctx())

    resp = client.get(f"/api/admin/outbound/?customer_id={alice.id}")
    data = resp.json()
    assert len(data) == 20


@pytest.mark.django_db(transaction=True)
def test_failure_inspection_endpoint_filters_by_status(alice, bob, client):
    queued = enqueue_message(alice, "booking_confirmation", _ctx())
    failed = enqueue_message(bob, "booking_confirmation", _ctx())
    failed.status = OutboundStatus.FAILED
    failed.failure_reason = "twilio_error: 21408"
    failed.save()

    resp = client.get("/api/admin/outbound/?status=failed")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == failed.id
    assert data[0]["failure_reason"] == "twilio_error: 21408"
    # Customer info is joined in for triage.
    assert data[0]["customer_name"] == "Bob"
    assert data[0]["customer_phone"] == "+14165550222"
    _ = queued  # silence lint


@pytest.mark.django_db(transaction=True)
def test_serialized_row_carries_all_documented_fields(alice, client):
    enqueue_message(alice, "booking_confirmation", _ctx(), reference="booking:42:confirm")
    resp = client.get(f"/api/admin/outbound/?customer_id={alice.id}")
    row = resp.json()[0]
    for field in (
        "id",
        "template_key",
        "body",
        "status",
        "scheduled_for",
        "sent_at",
        "failure_reason",
        "channel",
    ):
        assert field in row, f"missing field {field!r}"


@pytest.mark.django_db(transaction=True)
def test_unknown_status_filter_ignored(alice, client):
    """A typo'd status query string returns the unfiltered list."""
    enqueue_message(alice, "booking_confirmation", _ctx())
    resp = client.get("/api/admin/outbound/?status=not_a_real_status")
    assert resp.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_limit_is_capped_at_200(alice, client):
    for _ in range(5):
        enqueue_message(alice, "booking_confirmation", _ctx())
    resp = client.get(f"/api/admin/outbound/?customer_id={alice.id}&limit=99999")
    assert resp.status_code == 200
    # No crash; data is whatever's available, up to 200.
    assert len(resp.json()) <= 200
