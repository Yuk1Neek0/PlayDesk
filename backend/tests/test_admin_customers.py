"""Tests for the admin customers endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.models import Booking, BookingSource, BookingStatus, Customer, Resource, Store


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Admin Store", timezone="UTC", business_hours={})


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
def seeded(store):
    """Three customers: Alice (2 visits), Bob (1 visit), Cleo (0 visits)."""
    alice = Customer.objects.create(store=store, phone="+14165550111", name="Alice")
    bob = Customer.objects.create(store=store, phone="+14165550222", name="Bob")
    cleo = Customer.objects.create(store=store, phone="+14165550333", name="Cleo")
    return alice, bob, cleo


@pytest.fixture()
def seeded_with_visits(seeded, resource):
    alice, bob, _cleo = seeded
    base = datetime(2026, 11, 1, 18, tzinfo=UTC)
    Booking.objects.create(
        resource=resource, customer=alice, customer_name="Alice", customer_phone=alice.phone,
        start_time=base, end_time=base + timedelta(hours=1),
        status=BookingStatus.CONFIRMED, source=BookingSource.MANUAL,
    )
    Booking.objects.create(
        resource=resource, customer=alice, customer_name="Alice", customer_phone=alice.phone,
        start_time=base + timedelta(days=1), end_time=base + timedelta(days=1, hours=1),
        status=BookingStatus.CONFIRMED, source=BookingSource.AGENT,
    )
    Booking.objects.create(
        resource=resource, customer=bob, customer_name="Bob", customer_phone=bob.phone,
        start_time=base + timedelta(days=2), end_time=base + timedelta(days=2, hours=1),
        status=BookingStatus.CONFIRMED, source=BookingSource.MANUAL,
    )
    return seeded


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_list_returns_all_customers(seeded, client):
    resp = client.get("/api/admin/customers/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    names = {r["name"] for r in body["results"]}
    assert names == {"Alice", "Bob", "Cleo"}


@pytest.mark.django_db(transaction=True)
def test_list_orders_by_recency_after_visits(seeded_with_visits, client):
    resp = client.get("/api/admin/customers/")
    body = resp.json()
    # Bob's most recent visit is newest, so he leads; Alice next, Cleo last.
    names = [r["name"] for r in body["results"]]
    assert names == ["Bob", "Alice", "Cleo"]


@pytest.mark.django_db(transaction=True)
def test_search_by_name_substring(seeded, client):
    resp = client.get("/api/admin/customers/?q=ali")
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["name"] == "Alice"


@pytest.mark.django_db(transaction=True)
def test_search_by_phone_normalised(seeded, client):
    # Various surface formats of Alice's phone all resolve to her.
    for q in ["+14165550111", "(416) 555-0111", "4165550111"]:
        resp = client.get(f"/api/admin/customers/?q={q}")
        body = resp.json()
        assert body["count"] == 1, q
        assert body["results"][0]["name"] == "Alice"


@pytest.mark.django_db(transaction=True)
def test_search_with_no_match_returns_empty(seeded, client):
    resp = client.get("/api/admin/customers/?q=zzzz")
    assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_detail_embeds_visits_and_notes(seeded_with_visits, client):
    alice, _bob, _cleo = seeded_with_visits
    alice.notes.create(body="Prefers PS5", author=None)

    resp = client.get(f"/api/admin/customers/{alice.pk}/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == alice.pk
    assert len(body["visits"]) == 2
    # Newest visit first.
    assert body["visits"][0]["start_time"] >= body["visits"][1]["start_time"]
    assert len(body["notes"]) == 1
    assert body["notes"][0]["body"] == "Prefers PS5"
    assert body["notes"][0]["author_username"] is None


@pytest.mark.django_db(transaction=True)
def test_detail_404_for_missing_customer(db, client):
    resp = client.get("/api/admin/customers/99999/")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Add note
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_add_note_creates_and_returns(seeded, client):
    alice, _bob, _cleo = seeded
    resp = client.post(
        f"/api/admin/customers/{alice.pk}/notes/",
        {"body": "Needs accessible seating"},
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    note = resp.json()
    assert note["body"] == "Needs accessible seating"
    assert note["id"]
    alice.refresh_from_db()
    assert alice.notes.count() == 1


@pytest.mark.django_db(transaction=True)
def test_add_note_rejects_empty_body(seeded, client):
    alice, _bob, _cleo = seeded
    resp = client.post(
        f"/api/admin/customers/{alice.pk}/notes/",
        {"body": ""},
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db(transaction=True)
def test_add_note_404_for_missing_customer(db, client):
    resp = client.post(
        "/api/admin/customers/99999/notes/",
        {"body": "Doesn't matter"},
        content_type="application/json",
    )
    assert resp.status_code == 404
