"""Tests for ``GET /api/admin/stores/`` — the store-switcher list endpoint."""

from __future__ import annotations

import pytest

from core.models import Store


@pytest.mark.django_db
def test_returns_all_stores_sorted_by_slug(client):
    Store.objects.create(name="Charlie", slug="charlie", timezone="UTC", business_hours={})
    Store.objects.create(name="Alpha", slug="alpha", timezone="UTC", business_hours={})
    Store.objects.create(name="Bravo", slug="bravo", timezone="UTC", business_hours={})

    resp = client.get("/api/admin/stores/")
    assert resp.status_code == 200
    payload = resp.json()
    assert [s["slug"] for s in payload] == ["alpha", "bravo", "charlie"]
    for entry in payload:
        assert set(entry.keys()) == {"id", "slug", "name"}


@pytest.mark.django_db
def test_empty_db_returns_empty_list(client, db):
    resp = client.get("/api/admin/stores/")
    assert resp.status_code == 200
    assert resp.json() == []
