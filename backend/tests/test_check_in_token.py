"""Tests for the check-in token generator and backfill.

Covers:
- The pure-function generator stays inside the configured alphabet.
- 1000 calls yield 1000 distinct tokens (statistical smoke test).
- `generate_unique_check_in_token` retries on collision.
- Seeded bookings receive a token via the data migration.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from core.models import Booking, BookingStatus, Customer, Resource, Store
from core.tokens import (
    CHECK_IN_TOKEN_ALPHABET,
    CHECK_IN_TOKEN_LENGTH,
    generate_check_in_token,
    generate_unique_check_in_token,
)


def test_alphabet_excludes_ambiguous_chars():
    for c in "0O1Il":
        assert c not in CHECK_IN_TOKEN_ALPHABET


def test_generate_returns_token_of_configured_length_in_alphabet():
    token = generate_check_in_token()
    assert len(token) == CHECK_IN_TOKEN_LENGTH
    assert all(ch in CHECK_IN_TOKEN_ALPHABET for ch in token)


def test_generate_returns_distinct_tokens_over_1000_calls():
    # 32**8 = 1.1e12 keyspace — 1000 samples have a vanishing collision
    # probability. If this ever flakes the generator regressed.
    tokens = {generate_check_in_token() for _ in range(1000)}
    assert len(tokens) == 1000


@pytest.mark.django_db
def test_generate_unique_returns_db_unique_token():
    # No bookings exist — the first call succeeds without retrying.
    token = generate_unique_check_in_token()
    assert len(token) == CHECK_IN_TOKEN_LENGTH


@pytest.mark.django_db
def test_generate_unique_retries_on_collision():
    """One DB-collision should be retried, not bubbled up."""
    side_effects = [True, False]  # 1st collide, 2nd is free.

    class FakeManager:
        def filter(self, **_):
            return self

        def exists(self):
            return side_effects.pop(0)

    with mock.patch.object(Booking, "objects", FakeManager()):
        token = generate_unique_check_in_token(max_retries=5)
        assert len(token) == CHECK_IN_TOKEN_LENGTH
        # Verifies the retry loop consumed both side-effect entries.
        assert side_effects == []


@pytest.mark.django_db
def test_generate_unique_raises_after_max_retries():
    class AlwaysCollide:
        def filter(self, **_):
            return self

        def exists(self):
            return True

    with mock.patch.object(Booking, "objects", AlwaysCollide()):
        with pytest.raises(RuntimeError):
            generate_unique_check_in_token(max_retries=3)


@pytest.mark.django_db
def test_backfill_migration_populates_existing_booking_token():
    """The 0018 data migration assigns a token to every existing row.

    By the time this test runs, all migrations are applied — so any
    Booking we create here will get its token via
    `BookingCreateSerializer.create` (task #197) or stay NULL if
    created via raw ORM. We exercise the migration's contract by
    creating a token-less row, then re-running the backfill function.
    """
    store = Store.objects.create(name="Backfill Store", timezone="UTC", business_hours={})
    resource = Resource.objects.create(
        store=store,
        type="console",
        name="PS5",
        price_per_hour="50.00",
    )
    customer = Customer.objects.create(store=store, phone="+15551231234", name="Charlie")

    start = timezone.now() + timedelta(hours=1)
    end = start + timedelta(hours=1)
    booking = Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name="Charlie",
        customer_phone=customer.phone,
        start_time=start,
        end_time=end,
        status=BookingStatus.CONFIRMED,
    )

    # Simulate a legacy row by stripping the token.
    booking.check_in_token = None
    booking.save(update_fields=["check_in_token"])

    # Re-run the migration's `forward` function (idempotent, so safe).
    import importlib

    from django.apps import apps as global_apps

    backfill_mod = importlib.import_module("core.migrations.0018_backfill_check_in_token")
    backfill_mod.forward(global_apps, None)

    booking.refresh_from_db()
    assert booking.check_in_token is not None
    assert len(booking.check_in_token) == CHECK_IN_TOKEN_LENGTH
