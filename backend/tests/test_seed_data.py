"""Tests for the `seed_data` management command (multi-location v6).

Asserts the seed lands both stores with the expected slugs and that
re-running the command produces no duplicates.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command

from core.models import QRAction, Resource, Store


@pytest.mark.django_db
def test_seed_creates_both_stores_with_expected_slugs(capsys):
    call_command("seed_data")

    slugs = list(Store.objects.values_list("slug", flat=True).order_by("slug"))
    assert "playdesk-flagship" in slugs
    assert "playdesk-north" in slugs


@pytest.mark.django_db
def test_seed_is_idempotent_across_two_runs(capsys):
    call_command("seed_data")
    first_counts = {
        "stores": Store.objects.count(),
        "resources": Resource.objects.count(),
        "qr_actions": QRAction.objects.count(),
    }

    call_command("seed_data")
    second_counts = {
        "stores": Store.objects.count(),
        "resources": Resource.objects.count(),
        "qr_actions": QRAction.objects.count(),
    }

    assert first_counts == second_counts


@pytest.mark.django_db
def test_seed_resources_are_scoped_per_store(capsys):
    call_command("seed_data")

    flagship = Store.objects.get(slug="playdesk-flagship")
    north = Store.objects.get(slug="playdesk-north")

    # Flagship: 3 consoles + 1 room + 1 table = 5 resources.
    assert flagship.resources.count() == 5
    # North: 2 PS5 stations + 1 room = 3 resources.
    assert north.resources.count() == 3

    # No resource leaks across stores.
    north_names = set(north.resources.values_list("name", flat=True))
    flagship_names = set(flagship.resources.values_list("name", flat=True))
    assert north_names.isdisjoint(flagship_names)


@pytest.mark.django_db
def test_seed_seeds_default_qr_actions_per_store(capsys):
    call_command("seed_data")

    flagship = Store.objects.get(slug="playdesk-flagship")
    north = Store.objects.get(slug="playdesk-north")

    expected_kinds = {"review", "instagram", "wechat", "wifi"}
    assert set(flagship.qr_actions.values_list("kind", flat=True)) == expected_kinds
    assert set(north.qr_actions.values_list("kind", flat=True)) == expected_kinds
