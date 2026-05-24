"""Tests for the customer-portal loyalty endpoints (task #168).

The membership payload must match v4 admin's payload byte-for-byte
(same customer + same request) so the two surfaces share a single
source of truth. Redeem mirrors v4's atomic flow but with the customer
as author=None.
"""

from __future__ import annotations

import pytest

from core.memberships import award_points, current_balance
from core.middleware import CUSTOMER_COOKIE_NAME, sign_customer_session
from core.models import Customer, PointTransaction, Redemption, Reward, RewardTier, Store

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def flagship(db):
    return Store.objects.create(
        name="Mem Flagship", slug="memflag", timezone="UTC", business_hours={}
    )


@pytest.fixture()
def other_store(db):
    return Store.objects.create(
        name="Mem Other", slug="memother", timezone="UTC", business_hours={}
    )


@pytest.fixture()
def customer(flagship):
    return Customer.objects.create(store=flagship, phone="+15553334444", name="Carol")


@pytest.fixture()
def tiers(flagship):
    RewardTier.objects.create(
        store=flagship, name="Bronze", min_lifetime_points=0, perks_text="welcome", position=0
    )
    RewardTier.objects.create(
        store=flagship, name="Silver", min_lifetime_points=100, perks_text="vip", position=1
    )


@pytest.fixture()
def rewards(flagship, other_store):
    cheap = Reward.objects.create(store=flagship, name="Drink", cost_points=10, enabled=True)
    pricey = Reward.objects.create(store=flagship, name="Hour", cost_points=200, enabled=True)
    cross = Reward.objects.create(store=other_store, name="Other", cost_points=5, enabled=True)
    return cheap, pricey, cross


@pytest.fixture()
def auth_client(client, customer, flagship):
    token = sign_customer_session(customer.id, flagship.id)
    client.cookies[CUSTOMER_COOKIE_NAME] = token
    client.defaults["HTTP_X_PD_STORE_SLUG"] = flagship.slug
    return client


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_me_membership_401_without_cookie(client, flagship):
    client.defaults["HTTP_X_PD_STORE_SLUG"] = flagship.slug
    resp = client.get("/api/me/membership/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_me_membership_payload_matches_v4_admin(auth_client, customer, tiers, rewards):
    award_points(customer, 50, "booking", "seed")

    # Customer view.
    r_me = auth_client.get("/api/me/membership/")
    assert r_me.status_code == 200
    # Admin view (uses the same client — no cross-cookie since
    # admin endpoints don't read pd_customer_session, only headers).
    r_admin = auth_client.get(f"/api/admin/customers/{customer.pk}/membership/")
    assert r_admin.status_code == 200
    assert r_me.json() == r_admin.json()


# ---------------------------------------------------------------------------
# Redeem
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_me_redeem_happy_path(auth_client, customer, rewards):
    cheap, _, _ = rewards
    award_points(customer, 100, "adjustment", "seed")

    resp = auth_client.post(
        "/api/me/redeem/", data={"reward_id": cheap.id}, content_type="application/json"
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["balance"] == 90  # 100 - 10
    assert Redemption.objects.filter(customer=customer, reward=cheap).exists()
    # PointTransaction debit recorded.
    assert PointTransaction.objects.filter(
        customer=customer, source="redemption", delta=-10
    ).exists()


@pytest.mark.django_db
def test_me_redeem_insufficient_points_returns_409(auth_client, customer, rewards):
    _, pricey, _ = rewards
    # Customer has 0 points.
    resp = auth_client.post(
        "/api/me/redeem/", data={"reward_id": pricey.id}, content_type="application/json"
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "insufficient_points"
    assert body["balance"] == 0
    assert body["cost"] == 200


@pytest.mark.django_db
def test_me_redeem_cross_store_returns_400(auth_client, customer, rewards):
    _, _, cross = rewards
    award_points(customer, 100, "adjustment", "seed")
    resp = auth_client.post(
        "/api/me/redeem/", data={"reward_id": cross.id}, content_type="application/json"
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_me_redeem_author_is_none(auth_client, customer, rewards):
    cheap, _, _ = rewards
    award_points(customer, 100, "adjustment", "seed")
    resp = auth_client.post(
        "/api/me/redeem/", data={"reward_id": cheap.id}, content_type="application/json"
    )
    assert resp.status_code == 201
    # The new debit row has no staff/author — customer initiated.
    pt = PointTransaction.objects.get(
        customer=customer, source="redemption", reference=str(cheap.id)
    )
    assert pt.author is None
    red = Redemption.objects.get(transaction=pt)
    assert red.staff is None


@pytest.mark.django_db
def test_me_balance_after_redeem_matches(auth_client, customer, rewards):
    cheap, _, _ = rewards
    award_points(customer, 100, "adjustment", "seed")
    auth_client.post(
        "/api/me/redeem/", data={"reward_id": cheap.id}, content_type="application/json"
    )
    assert current_balance(customer) == 90
