"""Cross-store isolation invariants for the v6 admin surface.

Every admin endpoint that scopes to ``request.store`` must return ONLY
rows from the requested store, and must return 404 (not 200-with-empty-
payload, not 403) for detail accesses targeting another store's id.

The store is selected via the ``X-PD-Store-Slug`` header which the
``CurrentStoreMiddleware`` resolves first.

These tests are the contract the rest of the multi-location epic relies
on — if a new admin view ships without the filter, one of these breaks.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from campaigns.models import Campaign, CampaignStatus, Segment
from core.models import (
    Booking,
    BookingSource,
    BookingStatus,
    Conversation,
    Customer,
    Resource,
    Reward,
    RewardTier,
    Store,
)
from outbound.api import enqueue_message

# ---------------------------------------------------------------------------
# Fixtures — two stores, each populated with its own resources, bookings,
# customers, conversations, outbound rows, segments, campaigns, rewards.
# ---------------------------------------------------------------------------


@pytest.fixture()
def stores(db):
    a = Store.objects.create(name="Store A", slug="store-a", timezone="UTC", business_hours={})
    b = Store.objects.create(name="Store B", slug="store-b", timezone="UTC", business_hours={})
    return a, b


@pytest.fixture()
def resources(stores):
    a, b = stores
    ra = Resource.objects.create(
        store=a,
        type="console",
        name="A-PS5",
        capacity=4,
        price_per_hour="40.00",
        metadata={},
    )
    rb = Resource.objects.create(
        store=b,
        type="console",
        name="B-PS5",
        capacity=4,
        price_per_hour="40.00",
        metadata={},
    )
    return ra, rb


@pytest.fixture()
def customers(stores):
    a, b = stores
    alice = Customer.objects.create(store=a, phone="+14165550111", name="Alice A")
    bob = Customer.objects.create(store=b, phone="+14165550222", name="Bob B")
    return alice, bob


@pytest.fixture()
def bookings(resources, customers):
    ra, rb = resources
    alice, bob = customers
    base = datetime(2026, 11, 1, 18, tzinfo=UTC)
    ba = Booking.objects.create(
        resource=ra,
        customer=alice,
        customer_name="Alice A",
        customer_phone=alice.phone,
        start_time=base,
        end_time=base + timedelta(hours=1),
        status=BookingStatus.CONFIRMED,
        source=BookingSource.MANUAL,
    )
    bb = Booking.objects.create(
        resource=rb,
        customer=bob,
        customer_name="Bob B",
        customer_phone=bob.phone,
        start_time=base + timedelta(days=1),
        end_time=base + timedelta(days=1, hours=1),
        status=BookingStatus.CONFIRMED,
        source=BookingSource.MANUAL,
    )
    return ba, bb


@pytest.fixture()
def conversations(stores):
    a, b = stores
    ca = Conversation.objects.create(store=a, customer_identifier="alice-A")
    cb = Conversation.objects.create(store=b, customer_identifier="bob-B")
    return ca, cb


@pytest.fixture()
def outbound_rows(customers):
    alice, bob = customers
    ma = enqueue_message(
        alice,
        "booking_confirmation",
        {
            "customer_name": "Alice",
            "store_name": "Store A",
            "start_time": "2026-11-01 18:00",
            "resource_name": "A-PS5",
            "checkin_url": "http://localhost:3000/c/AAAA2345",
        },
    )
    mb = enqueue_message(
        bob,
        "booking_confirmation",
        {
            "customer_name": "Bob",
            "store_name": "Store B",
            "start_time": "2026-11-02 18:00",
            "resource_name": "B-PS5",
            "checkin_url": "http://localhost:3000/c/BBBB2345",
        },
    )
    return ma, mb


@pytest.fixture()
def segments(stores):
    a, b = stores
    sa = Segment.objects.create(store=a, name="A all", filter={})
    sb = Segment.objects.create(store=b, name="B all", filter={})
    return sa, sb


@pytest.fixture()
def campaigns(stores, segments):
    a, b = stores
    sa, sb = segments
    ca = Campaign.objects.create(
        store=a,
        name="A blast",
        segment=sa,
        body_template="hi {customer.name}",
        scheduled_for=timezone.now() + timedelta(hours=1),
        status=CampaignStatus.DRAFT,
    )
    cb = Campaign.objects.create(
        store=b,
        name="B blast",
        segment=sb,
        body_template="hi {customer.name}",
        scheduled_for=timezone.now() + timedelta(hours=1),
        status=CampaignStatus.DRAFT,
    )
    return ca, cb


@pytest.fixture()
def rewards(stores):
    a, b = stores
    ra = Reward.objects.create(store=a, name="A coffee", cost_points=10, enabled=True)
    rb = Reward.objects.create(store=b, name="B coffee", cost_points=10, enabled=True)
    return ra, rb


@pytest.fixture()
def tiers(stores):
    a, b = stores
    ta = RewardTier.objects.create(store=a, name="A bronze", min_lifetime_points=0, position=0)
    tb = RewardTier.objects.create(store=b, name="B bronze", min_lifetime_points=0, position=0)
    return ta, tb


@pytest.fixture()
def admin_client(client):
    User = get_user_model()
    user = User.objects.create_user(username="ops", password="x", is_staff=True)
    client.force_login(user)
    return client


def _hdr(store) -> dict:
    """Build the ``X-PD-Store-Slug`` header kwargs for ``client.get`` etc."""
    return {"HTTP_X_PD_STORE_SLUG": store.slug}


# ---------------------------------------------------------------------------
# Bookings — list scoped + detail 404 across stores
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_bookings_list_only_returns_current_store(stores, bookings, admin_client):
    a, b = stores
    ba, bb = bookings

    resp = admin_client.get("/api/admin/bookings/", **_hdr(a))
    ids = [row["id"] for row in resp.json()["results"]]
    assert ids == [ba.id]

    resp = admin_client.get("/api/admin/bookings/", **_hdr(b))
    ids = [row["id"] for row in resp.json()["results"]]
    assert ids == [bb.id]


@pytest.mark.django_db(transaction=True)
def test_booking_detail_404_across_stores(stores, bookings, admin_client):
    a, b = stores
    ba, bb = bookings

    # Store A asking for Store B's booking → 404 (NOT 200, NOT 403).
    resp = admin_client.get(f"/api/bookings/{bb.id}/", **_hdr(a))
    assert resp.status_code == 404, resp.content

    # And the other direction.
    resp = admin_client.get(f"/api/bookings/{ba.id}/", **_hdr(b))
    assert resp.status_code == 404

    # Sanity — each store still sees its own booking.
    resp = admin_client.get(f"/api/bookings/{ba.id}/", **_hdr(a))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Customers — list scoped + detail 404 across stores
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_customers_list_only_returns_current_store(stores, customers, admin_client):
    a, b = stores
    alice, bob = customers

    resp = admin_client.get("/api/admin/customers/", **_hdr(a))
    names = [row["name"] for row in resp.json()["results"]]
    assert names == [alice.name]

    resp = admin_client.get("/api/admin/customers/", **_hdr(b))
    names = [row["name"] for row in resp.json()["results"]]
    assert names == [bob.name]


@pytest.mark.django_db(transaction=True)
def test_customer_detail_404_across_stores(stores, customers, admin_client):
    a, b = stores
    alice, bob = customers

    resp = admin_client.get(f"/api/admin/customers/{bob.id}/", **_hdr(a))
    assert resp.status_code == 404
    resp = admin_client.get(f"/api/admin/customers/{alice.id}/", **_hdr(b))
    assert resp.status_code == 404
    # Owning store still resolves.
    resp = admin_client.get(f"/api/admin/customers/{alice.id}/", **_hdr(a))
    assert resp.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_customer_note_create_404_across_stores(stores, customers, admin_client):
    a, _b = stores
    _alice, bob = customers

    resp = admin_client.post(
        f"/api/admin/customers/{bob.id}/notes/",
        data=json.dumps({"body": "leak attempt"}),
        content_type="application/json",
        **_hdr(a),
    )
    assert resp.status_code == 404
    bob.refresh_from_db()
    assert bob.notes.count() == 0


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_conversations_list_only_returns_current_store(stores, conversations, admin_client):
    a, b = stores
    ca, cb = conversations

    resp = admin_client.get("/api/admin/conversations/", **_hdr(a))
    ids = [row["id"] for row in resp.json()["results"]]
    assert ids == [ca.id]

    resp = admin_client.get("/api/admin/conversations/", **_hdr(b))
    ids = [row["id"] for row in resp.json()["results"]]
    assert ids == [cb.id]


# ---------------------------------------------------------------------------
# Outbound messages
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_outbound_list_only_returns_current_store(stores, outbound_rows, admin_client):
    a, b = stores
    ma, mb = outbound_rows

    resp = admin_client.get("/api/admin/outbound/", **_hdr(a))
    ids = [row["id"] for row in resp.json()]
    assert ids == [ma.id]

    resp = admin_client.get("/api/admin/outbound/", **_hdr(b))
    ids = [row["id"] for row in resp.json()]
    assert ids == [mb.id]


@pytest.mark.django_db(transaction=True)
def test_admin_outbound_per_customer_404ish_across_stores(stores, outbound_rows, admin_client):
    """Requesting another store's customer_id returns an empty list — the
    customer-scope filter intersects with the store filter so the row is
    invisible. (No detail endpoint exists for outbound rows.)"""
    a, _b = stores
    _ma, mb = outbound_rows

    resp = admin_client.get(
        f"/api/admin/outbound/?customer_id={mb.customer_id}",
        **_hdr(a),
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Campaigns + segments
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_campaigns_list_only_returns_current_store(stores, campaigns, admin_client):
    a, b = stores
    ca, cb = campaigns

    resp = admin_client.get("/api/admin/campaigns/", **_hdr(a))
    ids = [row["id"] for row in resp.json()["results"]]
    assert ids == [ca.id]

    resp = admin_client.get("/api/admin/campaigns/", **_hdr(b))
    ids = [row["id"] for row in resp.json()["results"]]
    assert ids == [cb.id]


@pytest.mark.django_db(transaction=True)
def test_campaign_detail_404_across_stores(stores, campaigns, admin_client):
    a, _b = stores
    _ca, cb = campaigns

    resp = admin_client.get(f"/api/admin/campaigns/{cb.id}/", **_hdr(a))
    assert resp.status_code == 404

    # Send + cancel + runs all 404 when targeting another store's campaign.
    resp = admin_client.post(
        f"/api/admin/campaigns/{cb.id}/send/",
        data=json.dumps({"confirm": True}),
        content_type="application/json",
        **_hdr(a),
    )
    assert resp.status_code == 404

    resp = admin_client.post(
        f"/api/admin/campaigns/{cb.id}/cancel/",
        data="",
        content_type="application/json",
        **_hdr(a),
    )
    assert resp.status_code == 404

    resp = admin_client.get(f"/api/admin/campaigns/{cb.id}/runs/", **_hdr(a))
    assert resp.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_admin_segments_list_only_returns_current_store(stores, segments, admin_client):
    a, b = stores
    sa, sb = segments

    resp = admin_client.get("/api/admin/segments/", **_hdr(a))
    ids = [row["id"] for row in resp.json()["results"]]
    assert ids == [sa.id]

    resp = admin_client.get("/api/admin/segments/", **_hdr(b))
    ids = [row["id"] for row in resp.json()["results"]]
    assert ids == [sb.id]


@pytest.mark.django_db(transaction=True)
def test_segment_detail_404_across_stores(stores, segments, admin_client):
    a, _b = stores
    _sa, sb = segments
    resp = admin_client.get(f"/api/admin/segments/{sb.id}/", **_hdr(a))
    assert resp.status_code == 404
    resp = admin_client.get(f"/api/admin/segments/{sb.id}/preview/", **_hdr(a))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Memberships — customer + rewards + tiers
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_membership_view_404_across_stores(stores, customers, admin_client):
    a, _b = stores
    _alice, bob = customers
    resp = admin_client.get(f"/api/admin/customers/{bob.id}/membership/", **_hdr(a))
    assert resp.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_adjust_points_404_across_stores(stores, customers, admin_client):
    a, _b = stores
    _alice, bob = customers
    resp = admin_client.post(
        f"/api/admin/customers/{bob.id}/adjust-points/",
        data=json.dumps({"delta": 10, "reason": "test"}),
        content_type="application/json",
        **_hdr(a),
    )
    assert resp.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_rewards_list_only_returns_current_store(stores, rewards, admin_client):
    a, b = stores
    ra, rb = rewards

    resp = admin_client.get("/api/admin/rewards/", **_hdr(a))
    body = resp.json()
    items = body["results"] if isinstance(body, dict) and "results" in body else body
    names = {row["name"] for row in items}
    assert names == {ra.name}

    resp = admin_client.get("/api/admin/rewards/", **_hdr(b))
    body = resp.json()
    items = body["results"] if isinstance(body, dict) and "results" in body else body
    names = {row["name"] for row in items}
    assert names == {rb.name}


@pytest.mark.django_db(transaction=True)
def test_tiers_list_only_returns_current_store(stores, tiers, admin_client):
    a, b = stores
    ta, tb = tiers

    resp = admin_client.get("/api/admin/tiers/", **_hdr(a))
    body = resp.json()
    items = body["results"] if isinstance(body, dict) and "results" in body else body
    names = {row["name"] for row in items}
    assert names == {ta.name}

    resp = admin_client.get("/api/admin/tiers/", **_hdr(b))
    body = resp.json()
    items = body["results"] if isinstance(body, dict) and "results" in body else body
    names = {row["name"] for row in items}
    assert names == {tb.name}


# ---------------------------------------------------------------------------
# QR admin (actions list + detail)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_qr_actions_list_only_returns_current_store(stores, admin_client):
    a, b = stores
    from core.models import QRAction

    QRAction.objects.create(
        store=a, kind="review", label="A-review", target_url="https://a.example", position=0
    )
    QRAction.objects.create(
        store=b, kind="review", label="B-review", target_url="https://b.example", position=0
    )

    resp = admin_client.get("/api/admin/qr-actions/", **_hdr(a))
    labels = {row["label"] for row in resp.json()}
    assert labels == {"A-review"}


@pytest.mark.django_db(transaction=True)
def test_qr_action_detail_404_across_stores(stores, admin_client):
    a, b = stores
    from core.models import QRAction

    foreign = QRAction.objects.create(
        store=b, kind="review", label="B-review", target_url="https://b.example", position=0
    )

    resp = admin_client.patch(
        f"/api/admin/qr-actions/{foreign.id}/",
        data=json.dumps({"label": "hijacked"}),
        content_type="application/json",
        **_hdr(a),
    )
    assert resp.status_code == 404
    foreign.refresh_from_db()
    assert foreign.label == "B-review"


# ---------------------------------------------------------------------------
# Sanity: no detail endpoint leaks a different store's row via 200+empty.
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_no_cross_store_endpoint_returns_200_with_empty_payload(
    stores, bookings, customers, campaigns, segments, admin_client
):
    """Sweep — every detail endpoint with a cross-store id must 404, never
    200-with-empty-object (information-leak via timing / null-payload)."""
    a, _b = stores
    _ba, bb = bookings
    _alice, bob = customers
    _ca, cb = campaigns
    _sa, sb = segments

    cases = [
        f"/api/bookings/{bb.id}/",
        f"/api/admin/customers/{bob.id}/",
        f"/api/admin/customers/{bob.id}/membership/",
        f"/api/admin/campaigns/{cb.id}/",
        f"/api/admin/segments/{sb.id}/",
        f"/api/admin/segments/{sb.id}/preview/",
    ]
    for url in cases:
        resp = admin_client.get(url, **_hdr(a))
        assert resp.status_code == 404, f"{url} returned {resp.status_code}: {resp.content!r}"
