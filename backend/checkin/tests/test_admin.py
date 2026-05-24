"""Admin /api/admin/checkin/* endpoint tests (v11a, task #207)."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from checkin.models import RotatingCheckinKey
from checkin.services import mint_key
from core.models import Store

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("tests.urls"),
]


@pytest.fixture()
def staff_user(db):
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="rotcheck-staff",
        defaults={"is_staff": True, "is_active": True},
    )
    user.is_staff = True
    user.save()
    return user


@pytest.fixture()
def staff_client(staff_user):
    c = APIClient()
    c.force_login(staff_user)
    return c


@pytest.fixture()
def store(db):
    return Store.objects.create(
        name="Admin Door", slug="admin-door", timezone="UTC", business_hours={}
    )


def _hdr(store):
    return {"HTTP_X_PD_STORE_SLUG": store.slug}


def test_active_key_mints_on_first_call(staff_client, store):
    resp = staff_client.get("/api/admin/checkin/active-key/", **_hdr(store))
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"]
    assert body["qr_url"].endswith(f"/c-in/?k={body['key']}")
    assert body["rotation_minutes"] == 15
    assert RotatingCheckinKey.objects.filter(store=store).count() == 1


def test_active_key_returns_existing(staff_client, store):
    existing = mint_key(store)
    resp = staff_client.get("/api/admin/checkin/active-key/", **_hdr(store))
    assert resp.status_code == 200
    assert resp.json()["key"] == existing.key


def test_admin_rotate_force_mints(staff_client, store):
    first = mint_key(store)
    resp = staff_client.post("/api/admin/checkin/rotate/", **_hdr(store))
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"] != first.key
    first.refresh_from_db()
    assert first.superseded_at is not None


def test_admin_settings_updates_rotation_minutes(staff_client, store):
    resp = staff_client.patch(
        "/api/admin/checkin/settings/",
        {"rotation_minutes": 30},
        format="json",
        **_hdr(store),
    )
    assert resp.status_code == 200, resp.content
    store.refresh_from_db()
    assert store.checkin_rotation_minutes == 30
    assert resp.json()["rotation_minutes"] == 30


def test_admin_settings_validates_range(staff_client, store):
    resp = staff_client.patch(
        "/api/admin/checkin/settings/",
        {"rotation_minutes": 999},
        format="json",
        **_hdr(store),
    )
    assert resp.status_code == 400


def test_anon_blocked_by_staff_middleware(store):
    """Defence-in-depth: confirm StaffOnlyMiddleware gates the admin URL."""
    c = APIClient()
    resp = c.get("/api/admin/checkin/active-key/", **_hdr(store))
    assert resp.status_code == 401
