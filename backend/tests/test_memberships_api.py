"""Tests for the admin memberships endpoints (issue #110).

Covers the five surfaces wired up in ``backend/api/views_memberships.py``:
  - GET  /api/admin/customers/{id}/membership/
  - POST /api/admin/customers/{id}/adjust-points/
  - POST /api/admin/customers/{id}/redeem/
  - /api/admin/rewards/   (ViewSet)
  - /api/admin/tiers/     (ViewSet)
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from core.memberships import award_points, current_balance
from core.models import Customer, PointTransaction, Redemption, Reward, RewardTier, Store

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Mem API Store", timezone="UTC", business_hours={})


@pytest.fixture()
def other_store(db):
    return Store.objects.create(name="Other Store", timezone="UTC", business_hours={})


@pytest.fixture()
def customer(store):
    return Customer.objects.create(store=store, phone="+14165550111", name="Alice")


@pytest.fixture()
def admin_user(db):
    User = get_user_model()
    return User.objects.create_user(
        username="admin", password="x", is_staff=True, is_superuser=False
    )


@pytest.fixture()
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


@pytest.fixture()
def tiers(store):
    bronze = RewardTier.objects.create(
        store=store, name="Bronze", min_lifetime_points=0, perks_text="welcome", position=0
    )
    silver = RewardTier.objects.create(
        store=store, name="Silver", min_lifetime_points=100, perks_text="free drink", position=1
    )
    gold = RewardTier.objects.create(
        store=store, name="Gold", min_lifetime_points=500, perks_text="vip", position=2
    )
    return bronze, silver, gold


@pytest.fixture()
def rewards(store):
    cheap = Reward.objects.create(store=store, name="Free coffee", cost_points=10, enabled=True)
    pricey = Reward.objects.create(store=store, name="Free hour", cost_points=500, enabled=True)
    disabled = Reward.objects.create(store=store, name="Old promo", cost_points=5, enabled=False)
    return cheap, pricey, disabled


# ---------------------------------------------------------------------------
# Membership composite view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_membership_view_returns_full_payload(customer, tiers, rewards, admin_client):
    cheap, pricey, _ = rewards
    award_points(customer, 50, "booking", "b-1")
    award_points(customer, 25, "qr_click", "q-1")

    resp = admin_client.get(f"/api/admin/customers/{customer.pk}/membership/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["customer_id"] == customer.pk
    assert body["balance"] == 75
    assert body["lifetime_earned"] == 75
    # Bronze threshold is 0 — customer is in Bronze.
    assert body["tier"]["name"] == "Bronze"
    # Next tier is Silver @ 100.
    assert body["next_tier"]["name"] == "Silver"
    assert body["points_to_next_tier"] == 25
    # Two ledger rows, newest first.
    assert len(body["recent_transactions"]) == 2
    assert body["recent_transactions"][0]["delta"] == 25
    # Available rewards = enabled + affordable. Cheap (10) yes; pricey (500) no.
    ids = {r["id"] for r in body["available_rewards"]}
    assert cheap.id in ids
    assert pricey.id not in ids


@pytest.mark.django_db
def test_membership_view_404_for_missing_customer(admin_client):
    resp = admin_client.get("/api/admin/customers/99999/membership/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_membership_view_with_no_tiers(customer, admin_client):
    resp = admin_client.get(f"/api/admin/customers/{customer.pk}/membership/")
    body = resp.json()
    assert body["tier"] is None
    assert body["next_tier"] is None
    assert body["points_to_next_tier"] is None


# ---------------------------------------------------------------------------
# Adjust points
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_adjust_writes_transaction_with_author(customer, admin_client, admin_user):
    resp = admin_client.post(
        f"/api/admin/customers/{customer.pk}/adjust-points/",
        data=json.dumps({"delta": 25, "reason": "Birthday bonus"}),
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["balance"] == 25
    pt = PointTransaction.objects.get(pk=body["transaction_id"])
    assert pt.delta == 25
    assert pt.source == "adjustment"
    assert pt.reference == "Birthday bonus"
    assert pt.author_id == admin_user.id


@pytest.mark.django_db
def test_adjust_rejects_empty_reason(customer, admin_client):
    resp = admin_client.post(
        f"/api/admin/customers/{customer.pk}/adjust-points/",
        data=json.dumps({"delta": 10, "reason": "   "}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert PointTransaction.objects.filter(customer=customer).count() == 0


@pytest.mark.django_db
def test_adjust_rejects_zero_delta(customer, admin_client):
    resp = admin_client.post(
        f"/api/admin/customers/{customer.pk}/adjust-points/",
        data=json.dumps({"delta": 0, "reason": "noop"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_adjust_accepts_negative_delta(customer, admin_client):
    award_points(customer, 100, "booking", "b-1")
    resp = admin_client.post(
        f"/api/admin/customers/{customer.pk}/adjust-points/",
        data=json.dumps({"delta": -20, "reason": "manual correction"}),
        content_type="application/json",
    )
    assert resp.status_code == 201
    assert resp.json()["balance"] == 80


# ---------------------------------------------------------------------------
# Redeem
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_redeem_happy_path(customer, rewards, admin_client, admin_user):
    cheap, _, _ = rewards
    award_points(customer, 50, "booking", "b-1")

    resp = admin_client.post(
        f"/api/admin/customers/{customer.pk}/redeem/",
        data=json.dumps({"reward_id": cheap.id}),
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["balance"] == 40  # 50 - 10
    assert "redemption_id" in body
    redemption = Redemption.objects.get(pk=body["redemption_id"])
    assert redemption.reward_id == cheap.id
    assert redemption.staff_id == admin_user.id
    # One debit transaction was written.
    pt = PointTransaction.objects.get(pk=body["transaction_id"])
    assert pt.delta == -10
    assert pt.source == "redemption"


@pytest.mark.django_db
def test_redeem_insufficient_points_returns_409(customer, rewards, admin_client):
    cheap, _, _ = rewards
    # No points at all.
    resp = admin_client.post(
        f"/api/admin/customers/{customer.pk}/redeem/",
        data=json.dumps({"reward_id": cheap.id}),
        content_type="application/json",
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "insufficient_points"
    assert body["balance"] == 0
    assert body["cost"] == 10
    # No ledger or redemption rows were written.
    assert PointTransaction.objects.filter(customer=customer).count() == 0
    assert Redemption.objects.filter(customer=customer).count() == 0


@pytest.mark.django_db
def test_redeem_disabled_reward_rejected(customer, rewards, admin_client):
    _, _, disabled = rewards
    award_points(customer, 100, "booking", "b-1")
    resp = admin_client.post(
        f"/api/admin/customers/{customer.pk}/redeem/",
        data=json.dumps({"reward_id": disabled.id}),
        content_type="application/json",
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_redeem_cross_store_reward_rejected(customer, other_store, admin_client):
    award_points(customer, 100, "booking", "b-1")
    foreign = Reward.objects.create(store=other_store, name="Foreign", cost_points=10, enabled=True)
    resp = admin_client.post(
        f"/api/admin/customers/{customer.pk}/redeem/",
        data=json.dumps({"reward_id": foreign.id}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert current_balance(customer) == 100


# ---------------------------------------------------------------------------
# Rewards CRUD
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rewards_crud_round_trip(store, admin_client):
    # Create.
    resp = admin_client.post(
        "/api/admin/rewards/",
        data=json.dumps({"store": store.id, "name": "Snack", "cost_points": 20, "enabled": True}),
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    reward_id = resp.json()["id"]

    # Retrieve.
    resp = admin_client.get(f"/api/admin/rewards/{reward_id}/")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Snack"

    # Patch.
    resp = admin_client.patch(
        f"/api/admin/rewards/{reward_id}/",
        data=json.dumps({"enabled": False}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    # Delete.
    resp = admin_client.delete(f"/api/admin/rewards/{reward_id}/")
    assert resp.status_code == 204
    assert not Reward.objects.filter(pk=reward_id).exists()


@pytest.mark.django_db
def test_rewards_list_filters_by_store(store, other_store, admin_client):
    Reward.objects.create(store=store, name="A", cost_points=10)
    Reward.objects.create(store=store, name="B", cost_points=20)
    Reward.objects.create(store=other_store, name="C", cost_points=30)

    resp = admin_client.get(f"/api/admin/rewards/?store={store.id}")
    assert resp.status_code == 200
    body = resp.json()
    # DefaultRouter returns a list (no pagination configured for ViewSet).
    items = body["results"] if isinstance(body, dict) and "results" in body else body
    names = {r["name"] for r in items}
    assert names == {"A", "B"}


# ---------------------------------------------------------------------------
# Tiers CRUD
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tiers_crud_round_trip(store, admin_client):
    resp = admin_client.post(
        "/api/admin/tiers/",
        data=json.dumps(
            {
                "store": store.id,
                "name": "Silver",
                "min_lifetime_points": 100,
                "perks_text": "free drink",
                "position": 1,
            }
        ),
        content_type="application/json",
    )
    assert resp.status_code == 201, resp.content
    tier_id = resp.json()["id"]

    resp = admin_client.patch(
        f"/api/admin/tiers/{tier_id}/",
        data=json.dumps({"perks_text": "free drink + snack"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["perks_text"] == "free drink + snack"

    resp = admin_client.delete(f"/api/admin/tiers/{tier_id}/")
    assert resp.status_code == 204
    assert not RewardTier.objects.filter(pk=tier_id).exists()


@pytest.mark.django_db
def test_tiers_list_filters_by_store(store, other_store, admin_client):
    RewardTier.objects.create(store=store, name="Bronze", min_lifetime_points=0, position=0)
    RewardTier.objects.create(store=other_store, name="Gold", min_lifetime_points=0, position=0)

    resp = admin_client.get(f"/api/admin/tiers/?store={store.id}")
    body = resp.json()
    items = body["results"] if isinstance(body, dict) and "results" in body else body
    names = {r["name"] for r in items}
    assert names == {"Bronze"}


# ---------------------------------------------------------------------------
# Public tier badge — /api/qr/tier/?customer_id=&store=
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_qr_tier_badge_anonymous_returns_null(client):
    resp = client.get("/api/qr/tier/")
    assert resp.status_code == 200
    assert resp.json() == {"tier": None}


@pytest.mark.django_db
def test_qr_tier_badge_unknown_customer_returns_null(client, store):
    resp = client.get(f"/api/qr/tier/?customer_id=99999&store={store.id}")
    assert resp.status_code == 200
    assert resp.json() == {"tier": None}


@pytest.mark.django_db
def test_qr_tier_badge_returns_tier_when_resolvable(client, customer, tiers):
    bronze, _silver, _gold = tiers
    resp = client.get(f"/api/qr/tier/?customer_id={customer.id}&store={customer.store_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"]["id"] == bronze.id
    assert body["tier"]["name"] == "Bronze"


@pytest.mark.django_db
def test_qr_tier_badge_cross_store_returns_null(client, customer, other_store):
    # Customer is in `store`; asking for them with the other store returns null.
    resp = client.get(f"/api/qr/tier/?customer_id={customer.id}&store={other_store.id}")
    assert resp.status_code == 200
    assert resp.json() == {"tier": None}


@pytest.mark.django_db
def test_qr_tier_badge_no_tiers_returns_null(client, customer):
    resp = client.get(f"/api/qr/tier/?customer_id={customer.id}&store={customer.store_id}")
    assert resp.status_code == 200
    assert resp.json() == {"tier": None}
