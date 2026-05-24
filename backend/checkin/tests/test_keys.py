"""Rotation engine + resolver unit tests (v11a, task #204)."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from checkin.models import RotatingCheckinKey
from checkin.services import KEY_ALPHABET, get_active_key, mint_key, resolve_key
from core.models import Store

pytestmark = [pytest.mark.django_db]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(db):
    return Store.objects.create(
        name="Rot Store", slug="rot-store", timezone="UTC", business_hours={}
    )


@pytest.fixture()
def other_store(db):
    return Store.objects.create(
        name="Other Rot", slug="rot-other", timezone="UTC", business_hours={}
    )


# ---------------------------------------------------------------------------
# mint_key
# ---------------------------------------------------------------------------


def test_mint_key_creates_fresh_row(store):
    key = mint_key(store)
    assert key.pk is not None
    assert key.store_id == store.id
    assert len(key.key) == 10
    assert all(ch in KEY_ALPHABET for ch in key.key)
    assert key.superseded_at is None
    assert key.expires_at > timezone.now()


def test_mint_key_supersedes_previous(store):
    first = mint_key(store)
    second = mint_key(store)
    first.refresh_from_db()
    assert first.superseded_at is not None
    assert second.superseded_at is None
    assert first.key != second.key


def test_mint_key_does_not_supersede_other_stores(store, other_store):
    a = mint_key(store)
    mint_key(other_store)
    a.refresh_from_db()
    assert a.superseded_at is None


def test_mint_key_alphabet_excludes_ambiguous():
    for ch in "0O1Il":
        assert ch not in KEY_ALPHABET


# ---------------------------------------------------------------------------
# get_active_key
# ---------------------------------------------------------------------------


def test_get_active_key_none_when_no_keys(store):
    assert get_active_key(store) is None


def test_get_active_key_returns_fresh(store):
    minted = mint_key(store)
    active = get_active_key(store)
    assert active is not None
    assert active.pk == minted.pk


def test_get_active_key_prefers_fresh_over_superseded(store):
    old = mint_key(store)
    new = mint_key(store)
    active = get_active_key(store)
    assert active.pk == new.pk
    old.refresh_from_db()
    assert old.superseded_at is not None


def test_get_active_key_skips_expired(store):
    expired = mint_key(store)
    expired.expires_at = timezone.now() - timedelta(seconds=1)
    expired.save(update_fields=["expires_at"])
    assert get_active_key(store) is None


# ---------------------------------------------------------------------------
# resolve_key
# ---------------------------------------------------------------------------


def test_resolve_key_none_for_empty_or_unknown(store):
    assert resolve_key("") is None
    assert resolve_key(None) is None
    assert resolve_key("NEVERMINTED") is None


def test_resolve_key_returns_fresh_row(store):
    minted = mint_key(store)
    row = resolve_key(minted.key)
    assert row is not None
    assert row.pk == minted.pk


def test_resolve_key_returns_none_when_expired(store):
    minted = mint_key(store)
    minted.expires_at = timezone.now() - timedelta(seconds=1)
    minted.save(update_fields=["expires_at"])
    assert resolve_key(minted.key) is None


def test_resolve_key_within_grace_returns_row(store):
    first = mint_key(store)
    # Simulate "just got superseded".
    mint_key(store)
    first.refresh_from_db()
    assert first.superseded_at is not None
    # Within the default 60s grace, the first key still resolves.
    row = resolve_key(first.key)
    assert row is not None
    assert row.pk == first.pk


def test_resolve_key_outside_grace_returns_none(store):
    first = mint_key(store)
    mint_key(store)
    first.refresh_from_db()
    # Backdate the supersession past the grace window.
    first.superseded_at = timezone.now() - timedelta(seconds=120)
    first.save(update_fields=["superseded_at"])
    assert resolve_key(first.key) is None


# ---------------------------------------------------------------------------
# rotate_checkin_keys command
# ---------------------------------------------------------------------------


def _run_rotate(**kwargs) -> str:
    out = StringIO()
    call_command("rotate_checkin_keys", stdout=out, **kwargs)
    return out.getvalue()


def test_rotate_command_mints_when_none(store):
    _run_rotate(store=store.slug)
    assert RotatingCheckinKey.objects.filter(store=store).count() == 1


def test_rotate_command_no_op_when_fresh(store):
    mint_key(store)
    _run_rotate(store=store.slug)
    assert RotatingCheckinKey.objects.filter(store=store).count() == 1


def test_rotate_command_mints_when_interval_exceeded(store):
    minted = mint_key(store)
    # Backdate created_at past the rotation window.
    RotatingCheckinKey.objects.filter(pk=minted.pk).update(
        created_at=timezone.now() - timedelta(minutes=store.checkin_rotation_minutes + 1)
    )
    _run_rotate(store=store.slug)
    assert RotatingCheckinKey.objects.filter(store=store).count() == 2


def test_rotate_command_force_mints(store):
    mint_key(store)
    _run_rotate(store=store.slug, force=True)
    assert RotatingCheckinKey.objects.filter(store=store).count() == 2


def test_rotate_command_dry_run_does_not_write(store):
    _run_rotate(store=store.slug, dry_run=True)
    assert RotatingCheckinKey.objects.filter(store=store).count() == 0


def test_rotate_command_respects_store_filter(store, other_store):
    _run_rotate(store=store.slug)
    assert RotatingCheckinKey.objects.filter(store=store).count() == 1
    assert RotatingCheckinKey.objects.filter(store=other_store).count() == 0
