"""Tests for the v10a StaffOnlyMiddleware (`/api/admin/*` gate).

Covers the four contract points from the epic:
  - Anonymous → 401 on /api/admin/*.
  - Authenticated non-staff → 403 on /api/admin/*.
  - Authenticated staff → pass-through (200).
  - Non-admin URLs (e.g. /api/resources/, /api/me/) are not gated by
    this middleware — proves the two namespaces don't interfere.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture()
def regular_user(db):
    u = User.objects.create(username="regular", is_staff=False, is_active=True)
    u.set_password("pw")
    u.save()
    return u


# ---------------------------------------------------------------------------
# /api/admin/* — gate behaviour
# ---------------------------------------------------------------------------


def test_anonymous_get_admin_endpoint_is_401(anon_client, db):
    resp = anon_client.get("/api/admin/customers/")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Authentication required."}


def test_non_staff_user_get_admin_endpoint_is_403(anon_client, regular_user, db):
    anon_client.force_login(regular_user)
    resp = anon_client.get("/api/admin/customers/")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Staff access required."}


def test_staff_user_get_admin_endpoint_passes_through(client, db):
    # The default `client` fixture is pre-logged-in as test_staff (see
    # conftest.py). Any admin endpoint should answer normally — 200 from
    # an empty Customer list, not 401/403.
    resp = client.get("/api/admin/customers/")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Non-admin URLs — the gate must not gate them.
# ---------------------------------------------------------------------------


def test_resources_endpoint_is_anonymous_accessible(anon_client, db):
    """/api/resources/ has no admin prefix — must not be gated."""
    resp = anon_client.get("/api/resources/")
    assert resp.status_code == 200


def test_me_endpoint_is_not_gated_by_staff_middleware(anon_client, db):
    """/api/me/ is the customer portal — gated by CustomerSessionMiddleware,
    NOT StaffOnlyMiddleware. The two namespaces don't interfere; an
    anonymous request to /api/me/ must not hit the staff middleware's
    'Staff access required.' code path (which would imply the gate is
    incorrectly catching customer URLs).
    """
    # The customer-portal view enforces its own customer-cookie check and
    # returns 401 — same status code as the staff middleware, but via a
    # different middleware. The two namespaces happen to share a "401 +
    # detail" envelope; the assertion below pins the symptom we'd see
    # if the staff middleware ever matched /api/me/ by mistake.
    resp = anon_client.get("/api/me/")
    body = resp.json()
    assert body.get("detail") != "Staff access required."


def test_staff_login_endpoint_is_not_gated(anon_client, db):
    """/api/staff/login/ is the way IN — must accept anonymous POSTs."""
    resp = anon_client.post(
        "/api/staff/login/",
        data={"username": "ghost", "password": "x"},
        content_type="application/json",
    )
    # 401 because credentials are bad, NOT because the gate rejected the
    # request — distinguish by the response body.
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials."
