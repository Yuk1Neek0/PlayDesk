"""Tests for the One QR engagement endpoints."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Customer, QRAction, QRActionKind, QREvent, Store


@pytest.fixture()
def store(db):
    return Store.objects.create(
        name="QR Store",
        slug="qr-store",
        timezone="UTC",
        business_hours={},
        brand={"logo_url": "https://example.com/logo.png", "accent": "oklch(0.78 0.16 200)"},
    )


@pytest.fixture()
def actions(store):
    a1 = QRAction.objects.create(
        store=store,
        kind=QRActionKind.REVIEW,
        label="Review",
        target_url="https://example.com/review",
        position=0,
        reward_points=10,
    )
    a2 = QRAction.objects.create(
        store=store,
        kind=QRActionKind.INSTAGRAM,
        label="IG",
        target_url="https://example.com/ig",
        position=1,
        reward_points=5,
    )
    a3 = QRAction.objects.create(
        store=store,
        kind=QRActionKind.WIFI,
        label="WiFi",
        target_url="https://example.com/wifi",
        position=2,
        reward_points=1,
    )
    return a1, a2, a3


# ---------------------------------------------------------------------------
# Public landing payload
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_public_payload_returns_branded_actions(actions, client, store):
    resp = client.get(f"/api/qr/{store.slug}/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["store"]["slug"] == store.slug
    assert body["store"]["brand"]["accent"]
    labels = [a["label"] for a in body["actions"]]
    assert labels == ["Review", "IG", "WiFi"]


@pytest.mark.django_db
def test_public_payload_omits_disabled_actions(actions, client, store):
    a1, _a2, _a3 = actions
    a1.enabled = False
    a1.save()
    resp = client.get(f"/api/qr/{store.slug}/")
    labels = [a["label"] for a in resp.json()["actions"]]
    assert "Review" not in labels


@pytest.mark.django_db
def test_public_payload_404_for_unknown_slug(db, client):
    assert client.get("/api/qr/no-such-store/").status_code == 404


# ---------------------------------------------------------------------------
# Event tracking
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_anonymous_scan_event_records(actions, client, store):
    resp = client.post(
        "/api/qr/event/",
        {"slug": store.slug, "kind": "scan"},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert QREvent.objects.filter(store=store, kind="scan").count() == 1
    assert QREvent.objects.filter(customer__isnull=False).count() == 0


@pytest.mark.django_db
def test_click_event_requires_action_id(actions, client, store):
    resp = client.post(
        "/api/qr/event/",
        {"slug": store.slug, "kind": "click"},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "action_id" in resp.json()


@pytest.mark.django_db
def test_click_with_pd_customer_cookie_links_and_tags(actions, client, store):
    a1, _a2, _a3 = actions
    customer = Customer.objects.create(store=store, phone="+14165550111", name="Alice")
    client.cookies["pd_customer"] = str(customer.pk)
    resp = client.post(
        "/api/qr/event/",
        {"slug": store.slug, "kind": "click", "action_id": a1.id},
        content_type="application/json",
    )
    assert resp.status_code == 201
    ev = QREvent.objects.get(kind="click", action=a1)
    assert ev.customer_id == customer.pk
    customer.refresh_from_db()
    assert "qr:review" in customer.tags


@pytest.mark.django_db
def test_click_with_invalid_cookie_falls_back_to_anonymous(actions, client, store):
    a1, _a2, _a3 = actions
    client.cookies["pd_customer"] = "99999"
    resp = client.post(
        "/api/qr/event/",
        {"slug": store.slug, "kind": "click", "action_id": a1.id},
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert QREvent.objects.filter(customer__isnull=True, kind="click").count() == 1


@pytest.mark.django_db
def test_unknown_slug_returns_404(db, client):
    resp = client.post(
        "/api/qr/event/",
        {"slug": "nope", "kind": "scan"},
        content_type="application/json",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin CRUD + reorder
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_list_filters_by_store(actions, client, store):
    other_store = Store.objects.create(
        name="Other", slug="other", timezone="UTC", business_hours={}
    )
    QRAction.objects.create(
        store=other_store,
        kind=QRActionKind.REVIEW,
        label="Other review",
        target_url="https://example.com/r",
        position=0,
    )
    resp = client.get(f"/api/admin/qr-actions/?store={store.id}")
    labels = [a["label"] for a in resp.json()]
    assert "Other review" not in labels
    assert len(labels) == 3


@pytest.mark.django_db
def test_admin_create_appends_to_end(actions, client, store):
    resp = client.post(
        "/api/admin/qr-actions/",
        {
            "store": store.id,
            "kind": "tiktok",
            "label": "TikTok",
            "target_url": "https://example.com/tt",
        },
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["position"] == 3  # appended after 0,1,2


@pytest.mark.django_db
def test_admin_reorder_renumbers_atomically(actions, client, store):
    a1, a2, a3 = actions  # positions 0, 1, 2
    # Move a1 (Review, position 0) to the end.
    resp = client.patch(
        f"/api/admin/qr-actions/{a1.id}/",
        {"position": 2},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    positions = list(
        QRAction.objects.filter(store=store).order_by("position").values_list("kind", "position")
    )
    # IG → 0, WiFi → 1, Review → 2
    assert positions == [("instagram", 0), ("wifi", 1), ("review", 2)]


@pytest.mark.django_db
def test_admin_delete_compacts_positions(actions, client, store):
    a1, a2, a3 = actions
    resp = client.delete(f"/api/admin/qr-actions/{a2.id}/")
    assert resp.status_code == 204
    positions = list(
        QRAction.objects.filter(store=store).order_by("position").values_list("kind", "position")
    )
    assert positions == [("review", 0), ("wifi", 1)]


@pytest.mark.django_db
def test_admin_patch_label_keeps_position(actions, client, store):
    a1, _a2, _a3 = actions
    resp = client.patch(
        f"/api/admin/qr-actions/{a1.id}/",
        {"label": "Renamed"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    a1.refresh_from_db()
    assert a1.label == "Renamed"
    assert a1.position == 0


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_analytics_zero_safe(client, store):
    """No events yet: every numeric field is 0, never NaN."""
    resp = client.get(f"/api/admin/qr-analytics/?store={store.id}&days=7")
    body = resp.json()
    assert body["scans"] == 0
    assert body["clicks"] == 0
    assert body["engagement_rate"] == 0.0
    assert body["per_action"] == []


@pytest.mark.django_db
def test_analytics_breakdown_per_action(actions, client, store):
    a1, a2, _a3 = actions
    QREvent.objects.create(store=store, kind="scan")
    QREvent.objects.create(store=store, kind="scan")
    QREvent.objects.create(store=store, kind="click", action=a1)
    QREvent.objects.create(store=store, kind="click", action=a1)
    QREvent.objects.create(store=store, kind="click", action=a2)

    resp = client.get(f"/api/admin/qr-analytics/?store={store.id}&days=30")
    body = resp.json()
    assert body["scans"] == 2
    assert body["clicks"] == 3
    assert body["engagement_rate"] == 1.5  # 3 clicks / 2 scans
    by_action = {row["action_id"]: row["clicks"] for row in body["per_action"]}
    assert by_action[a1.id] == 2
    assert by_action[a2.id] == 1


@pytest.mark.django_db
def test_analytics_window_filters_events(actions, client, store):
    a1, _a2, _a3 = actions
    QREvent.objects.create(store=store, kind="click", action=a1)
    old = QREvent.objects.create(store=store, kind="click", action=a1)
    QREvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=14))

    body = client.get(f"/api/admin/qr-analytics/?store={store.id}&days=7").json()
    assert body["clicks"] == 1  # only the recent one
