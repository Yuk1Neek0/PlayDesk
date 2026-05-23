"""Integration tests for the campaigns admin endpoints."""

from __future__ import annotations

import pytest

from campaigns.models import Campaign, CampaignRunStatus, CampaignStatus, Segment
from campaigns.send import _stub_impl, force_send_impl
from core.models import Customer, Store


@pytest.fixture()
def store(db):
    return Store.objects.create(name="View Store", timezone="UTC", business_hours={})


@pytest.fixture()
def other_store(db):
    return Store.objects.create(name="Other Store", timezone="UTC", business_hours={})


@pytest.fixture()
def segment(store):
    return Segment.objects.create(store=store, name="All", filter={})


@pytest.fixture()
def customers(store):
    return [
        Customer.objects.create(store=store, phone=f"+1416555{i:04d}", name=f"C{i}")
        for i in range(3)
    ]


# ---------------------------------------------------------------------------
# Segments CRUD
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_segment_crud_round_trip(store, client):
    # Create
    resp = client.post(
        "/api/admin/segments/",
        {"store_id": store.pk, "name": "VIPs", "filter": {"tags_include": ["vip"]}},
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    seg_id = resp.json()["id"]

    # List
    resp = client.get("/api/admin/segments/")
    assert resp.status_code == 200
    assert any(s["id"] == seg_id for s in resp.json()["results"])

    # Retrieve
    resp = client.get(f"/api/admin/segments/{seg_id}/")
    assert resp.status_code == 200
    assert resp.json()["name"] == "VIPs"

    # Patch
    resp = client.patch(
        f"/api/admin/segments/{seg_id}/",
        {"name": "VIPs v2"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "VIPs v2"

    # Delete
    resp = client.delete(f"/api/admin/segments/{seg_id}/")
    assert resp.status_code == 204


@pytest.mark.django_db(transaction=True)
def test_segment_rejects_unknown_filter_key(store, client):
    resp = client.post(
        "/api/admin/segments/",
        {"store_id": store.pk, "name": "X", "filter": {"bogus": 1}},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert "filter" in resp.json()


@pytest.mark.django_db(transaction=True)
def test_segment_preview_shape(store, segment, customers, client):
    resp = client.get(f"/api/admin/segments/{segment.pk}/preview/?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert len(body["sample"]) == 2
    assert {"id", "name", "phone"}.issubset(body["sample"][0].keys())


@pytest.mark.django_db(transaction=True)
def test_segment_preview_404(client, db):
    resp = client.get("/api/admin/segments/9999/preview/")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Campaigns CRUD
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_campaign_crud_round_trip(store, segment, client):
    resp = client.post(
        "/api/admin/campaigns/",
        {
            "store_id": store.pk,
            "segment_id": segment.pk,
            "name": "May Drop",
            "body_template": "Hi {customer.name}",
        },
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    cid = resp.json()["id"]
    assert resp.json()["status"] == "draft"

    resp = client.patch(
        f"/api/admin/campaigns/{cid}/",
        {"name": "May Drop v2"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "May Drop v2"


@pytest.mark.django_db(transaction=True)
def test_campaign_create_rejects_empty_body(store, segment, client):
    resp = client.post(
        "/api/admin/campaigns/",
        {
            "store_id": store.pk,
            "segment_id": segment.pk,
            "name": "Empty",
            "body_template": "   ",
        },
        content_type="application/json",
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Campaign send
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_campaign_send_happy_path(store, segment, customers, client):
    campaign = Campaign.objects.create(
        store=store, segment=segment, name="X", body_template="Hi {customer.name}"
    )
    with force_send_impl(_stub_impl):
        resp = client.post(
            f"/api/admin/campaigns/{campaign.pk}/send/",
            {"confirm": True},
            content_type="application/json",
        )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["sent"] == 3
    assert body["snapshot_count"] == 3

    campaign.refresh_from_db()
    assert campaign.status == CampaignStatus.SENT


@pytest.mark.django_db(transaction=True)
def test_campaign_send_requires_confirm(store, segment, customers, client):
    campaign = Campaign.objects.create(store=store, segment=segment, name="X", body_template="Hi")
    resp = client.post(
        f"/api/admin/campaigns/{campaign.pk}/send/",
        {},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "confirmation_required"


@pytest.mark.django_db(transaction=True)
def test_campaign_send_twice_409(store, segment, customers, client):
    campaign = Campaign.objects.create(
        store=store, segment=segment, name="X", body_template="Hi {customer.name}"
    )
    with force_send_impl(_stub_impl):
        client.post(
            f"/api/admin/campaigns/{campaign.pk}/send/",
            {"confirm": True},
            content_type="application/json",
        )
        resp = client.post(
            f"/api/admin/campaigns/{campaign.pk}/send/",
            {"confirm": True},
            content_type="application/json",
        )
    assert resp.status_code == 409
    assert resp.json()["error"] == "campaign_already_sent"


@pytest.mark.django_db(transaction=True)
def test_campaign_patch_after_send_409(store, segment, customers, client):
    campaign = Campaign.objects.create(
        store=store, segment=segment, name="X", body_template="Hi {customer.name}"
    )
    with force_send_impl(_stub_impl):
        client.post(
            f"/api/admin/campaigns/{campaign.pk}/send/",
            {"confirm": True},
            content_type="application/json",
        )
    resp = client.patch(
        f"/api/admin/campaigns/{campaign.pk}/",
        {"name": "New name"},
        content_type="application/json",
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Campaign cancel
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_campaign_cancel_draft(store, segment, client):
    campaign = Campaign.objects.create(store=store, segment=segment, name="X", body_template="Hi")
    resp = client.post(f"/api/admin/campaigns/{campaign.pk}/cancel/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.django_db(transaction=True)
def test_campaign_cancel_after_sent_409(store, segment, customers, client):
    campaign = Campaign.objects.create(
        store=store, segment=segment, name="X", body_template="Hi {customer.name}"
    )
    with force_send_impl(_stub_impl):
        client.post(
            f"/api/admin/campaigns/{campaign.pk}/send/",
            {"confirm": True},
            content_type="application/json",
        )
    resp = client.post(f"/api/admin/campaigns/{campaign.pk}/cancel/")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Runs listing
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_runs_list_pagination_and_filter(store, segment, customers, client):
    campaign = Campaign.objects.create(
        store=store, segment=segment, name="X", body_template="Hi {customer.name}"
    )
    with force_send_impl(_stub_impl):
        client.post(
            f"/api/admin/campaigns/{campaign.pk}/send/",
            {"confirm": True},
            content_type="application/json",
        )
    resp = client.get(f"/api/admin/campaigns/{campaign.pk}/runs/?page_size=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert len(body["results"]) == 2

    resp = client.get(f"/api/admin/campaigns/{campaign.pk}/runs/?status={CampaignRunStatus.SENT}")
    assert resp.status_code == 200
    assert resp.json()["count"] == 3


@pytest.mark.django_db(transaction=True)
def test_runs_list_404_for_missing_campaign(client, db):
    resp = client.get("/api/admin/campaigns/9999/runs/")
    assert resp.status_code == 404
