"""Tests for the public store-brand endpoint (/api/public/store-brand/)."""

from __future__ import annotations

import pytest

from core.models import Store

URL = "/api/public/store-brand/"


@pytest.mark.django_db
def test_default_store_with_empty_brand_returns_nulls(client):
    Store.objects.create(name="Empty Brand Store", timezone="UTC", business_hours={}, brand={})
    resp = client.get(URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"name": "Empty Brand Store", "logo_url": None, "accent": None}


@pytest.mark.django_db
def test_store_with_valid_brand_surfaces_logo_and_accent(client):
    Store.objects.create(
        name="Branded Store",
        timezone="UTC",
        business_hours={},
        brand={
            "logo_url": "https://cdn.example.com/logo.png",
            "accent": "oklch(0.78 0.16 200)",
        },
    )
    resp = client.get(URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Branded Store"
    assert body["logo_url"] == "https://cdn.example.com/logo.png"
    assert body["accent"] == "oklch(0.78 0.16 200)"


@pytest.mark.django_db
def test_malicious_accent_is_nulled(client):
    Store.objects.create(
        name="XSS Store",
        timezone="UTC",
        business_hours={},
        brand={"accent": "javascript:alert(1)"},
    )
    resp = client.get(URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["accent"] is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "accent",
    [
        "#aabbcc",
        "#AABBCC",
        "rgb(10, 20, 30)",
        "oklch(0.6 0.1 100)",
    ],
)
def test_valid_accent_formats_pass(client, accent):
    Store.objects.create(
        name=f"S-{accent}",
        timezone="UTC",
        business_hours={},
        brand={"accent": accent},
    )
    resp = client.get(URL)
    assert resp.json()["accent"] == accent


@pytest.mark.django_db
@pytest.mark.parametrize(
    "accent",
    [
        "red",
        "#abc",  # short hex not in grammar
        "oklch 0.5 0.1 200",  # missing parens
        "javascript:alert(1)",
        "",
        123,
    ],
)
def test_invalid_accent_formats_are_nulled(client, accent):
    Store.objects.create(
        name=f"S-{accent}",
        timezone="UTC",
        business_hours={},
        brand={"accent": accent},
    )
    resp = client.get(URL)
    assert resp.json()["accent"] is None


@pytest.mark.django_db
def test_anonymous_request_is_200(client):
    Store.objects.create(name="Anon Store", timezone="UTC", business_hours={})
    resp = client.get(URL)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_response_carries_cache_header(client):
    Store.objects.create(name="Cacheable Store", timezone="UTC", business_hours={})
    resp = client.get(URL)
    assert resp["Cache-Control"] == "public, max-age=60"


# ── ?store=<slug> query-param branch (task #162) ──────────────────────────


@pytest.mark.django_db
def test_store_query_param_picks_the_named_store(client):
    Store.objects.create(
        name="Alpha",
        slug="alpha",
        timezone="UTC",
        business_hours={},
        brand={"accent": "#aabbcc"},
    )
    Store.objects.create(
        name="Beta",
        slug="beta",
        timezone="UTC",
        business_hours={},
        brand={"accent": "#112233"},
    )
    # No header / cookie → middleware fallback would pick Alpha (alphabetic
    # first), but the query param wins.
    resp = client.get(URL + "?store=beta")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Beta"
    assert body["accent"] == "#112233"


@pytest.mark.django_db
def test_unknown_store_query_param_falls_through_to_middleware(client):
    Store.objects.create(name="Alpha", slug="alpha", timezone="UTC", business_hours={})
    resp = client.get(URL + "?store=does-not-exist")
    assert resp.status_code == 200
    # Fallback: the alphabetically-first store.
    assert resp.json()["name"] == "Alpha"


@pytest.mark.django_db
def test_empty_store_query_param_falls_through(client):
    Store.objects.create(name="Alpha", slug="alpha", timezone="UTC", business_hours={})
    resp = client.get(URL + "?store=")
    assert resp.json()["name"] == "Alpha"


# ── /api/public/default-store/ (task #162) ────────────────────────────────


DEFAULT_URL = "/api/public/default-store/"


@pytest.mark.django_db
def test_default_store_endpoint_returns_alphabetically_first_slug(client):
    Store.objects.create(name="Zeta", slug="zeta", timezone="UTC", business_hours={})
    Store.objects.create(name="Alpha", slug="alpha", timezone="UTC", business_hours={})
    resp = client.get(DEFAULT_URL)
    assert resp.status_code == 200
    assert resp.json() == {"slug": "alpha"}


@pytest.mark.django_db
def test_default_store_endpoint_returns_null_when_no_stores(client):
    resp = client.get(DEFAULT_URL)
    assert resp.status_code == 200
    assert resp.json() == {"slug": None}


@pytest.mark.django_db
def test_default_store_endpoint_is_cacheable(client):
    Store.objects.create(name="One", slug="one", timezone="UTC", business_hours={})
    resp = client.get(DEFAULT_URL)
    assert resp["Cache-Control"] == "public, max-age=60"
