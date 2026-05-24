"""Tests for the v10a staff-auth endpoints.

Covers /api/staff/{login,logout,me}/:
  - login happy path sets a session and /me/ subsequently returns it.
  - wrong password → 401, no session.
  - non-staff user → 403.
  - logout → /me/ subsequently 401.
  - rate limit: 6th attempt within 15 min → 429.
  - /me/ anonymous → 401.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

User = get_user_model()


@pytest.fixture(autouse=True)
def _clear_cache():
    """Per-test cache flush so rate-limit keys don't leak between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture()
def staff_user(db):
    u = User.objects.create(username="alice", is_staff=True, is_active=True)
    u.set_password("alice-pw")
    u.save()
    return u


@pytest.fixture()
def regular_user(db):
    u = User.objects.create(username="bob", is_staff=False, is_active=True)
    u.set_password("bob-pw")
    u.save()
    return u


# ---------------------------------------------------------------------------
# /api/staff/login/
# ---------------------------------------------------------------------------


def test_login_happy_path_sets_session(client, staff_user):
    resp = client.post(
        reverse("api:staff-login"),
        data={"username": "alice", "password": "alice-pw"},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["username"] == "alice"
    assert body["is_staff"] is True
    assert body["is_superuser"] is False
    assert body["id"] == staff_user.id

    # Login must set the Django session cookie on the response so the
    # browser carries it forward to every subsequent admin request.
    assert "sessionid" in resp.cookies

    # Subsequent /me/ on the same client returns the user.
    me = client.get(reverse("api:staff-me"))
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


def test_login_wrong_password_is_401(client, staff_user):
    resp = client.post(
        reverse("api:staff-login"),
        data={"username": "alice", "password": "WRONG"},
        content_type="application/json",
    )
    assert resp.status_code == 401
    # No session created → /me/ is anonymous.
    me = client.get(reverse("api:staff-me"))
    assert me.status_code == 401


def test_login_unknown_username_is_401(client, db):
    resp = client.post(
        reverse("api:staff-login"),
        data={"username": "ghost", "password": "x"},
        content_type="application/json",
    )
    assert resp.status_code == 401


def test_login_non_staff_user_is_403(client, regular_user):
    resp = client.post(
        reverse("api:staff-login"),
        data={"username": "bob", "password": "bob-pw"},
        content_type="application/json",
    )
    assert resp.status_code == 403
    # No session created.
    me = client.get(reverse("api:staff-me"))
    assert me.status_code == 401


# ---------------------------------------------------------------------------
# /api/staff/logout/
# ---------------------------------------------------------------------------


def test_logout_clears_session(client, staff_user):
    client.post(
        reverse("api:staff-login"),
        data={"username": "alice", "password": "alice-pw"},
        content_type="application/json",
    )
    assert client.get(reverse("api:staff-me")).status_code == 200

    resp = client.post(reverse("api:staff-logout"))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    me = client.get(reverse("api:staff-me"))
    assert me.status_code == 401


def test_logout_when_already_anonymous_is_200(client, db):
    resp = client.post(reverse("api:staff-logout"))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/staff/me/
# ---------------------------------------------------------------------------


def test_me_anonymous_is_401(client, db):
    resp = client.get(reverse("api:staff-me"))
    assert resp.status_code == 401


def test_me_non_staff_authenticated_is_401(client, regular_user):
    # Force-login a non-staff user via Django's test client.
    client.force_login(regular_user)
    resp = client.get(reverse("api:staff-me"))
    # Non-staff session is treated as unauthenticated for admin purposes.
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Rate limit — 5 attempts per username per 15 min.
# ---------------------------------------------------------------------------


def test_login_rate_limit_blocks_sixth_attempt(client, staff_user):
    # Five wrong attempts → all 401.
    for _ in range(5):
        resp = client.post(
            reverse("api:staff-login"),
            data={"username": "alice", "password": "WRONG"},
            content_type="application/json",
        )
        assert resp.status_code == 401

    # Sixth attempt — even with the right password — gets 429.
    resp = client.post(
        reverse("api:staff-login"),
        data={"username": "alice", "password": "alice-pw"},
        content_type="application/json",
    )
    assert resp.status_code == 429


def test_login_rate_limit_resets_on_success(client, staff_user):
    # Four wrong attempts (still under the limit).
    for _ in range(4):
        client.post(
            reverse("api:staff-login"),
            data={"username": "alice", "password": "WRONG"},
            content_type="application/json",
        )

    # Right password works AND clears the counter.
    ok = client.post(
        reverse("api:staff-login"),
        data={"username": "alice", "password": "alice-pw"},
        content_type="application/json",
    )
    assert ok.status_code == 200

    # Five subsequent wrong attempts are allowed again because the
    # counter reset on success.
    for _ in range(5):
        resp = client.post(
            reverse("api:staff-login"),
            data={"username": "alice", "password": "WRONG"},
            content_type="application/json",
        )
        assert resp.status_code == 401
