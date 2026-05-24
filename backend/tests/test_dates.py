"""Tests for ``core.dates.today_local``."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest

from core.dates import today_local
from core.models import Store


def _at_utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.mark.django_db
def test_today_local_returns_store_local_date_when_utc_is_next_day():
    """UTC has already rolled into 2026-06-02, but America/Toronto is still
    2026-06-01 — the helper must return the store-local date, not UTC's.
    """
    store = Store.objects.create(name="TZ Store A", timezone="America/Toronto")
    # 03:00 UTC on 2026-06-02 == 23:00 EDT on 2026-06-01.
    with patch("core.dates.timezone.now", return_value=_at_utc(2026, 6, 2, 3, 0)):
        assert today_local(store) == date(2026, 6, 1)


@pytest.mark.django_db
def test_today_local_returns_store_local_date_when_utc_is_same_day():
    """Early-evening UTC on 2026-06-01 == same day in America/Toronto."""
    store = Store.objects.create(name="TZ Store B", timezone="America/Toronto")
    # 20:00 UTC on 2026-06-01 == 16:00 EDT same day.
    with patch("core.dates.timezone.now", return_value=_at_utc(2026, 6, 1, 20, 0)):
        assert today_local(store) == date(2026, 6, 1)


@pytest.mark.django_db
def test_today_local_falls_back_to_utc_on_invalid_timezone(caplog):
    store = Store.objects.create(name="TZ Store C", timezone="Invalid/Timezone")
    with (
        caplog.at_level(logging.WARNING, logger="core.dates"),
        patch("core.dates.timezone.now", return_value=_at_utc(2026, 6, 2, 3, 0)),
    ):
        assert today_local(store) == date(2026, 6, 2)
    assert any("invalid timezone" in rec.message.lower() for rec in caplog.records)


@pytest.mark.django_db
def test_today_local_falls_back_to_utc_on_empty_timezone(caplog):
    # The Store model has a default of "UTC"; force a literal empty value
    # to exercise the empty-string branch without violating NOT NULL.
    store = Store.objects.create(name="TZ Store D", timezone="UTC")
    store.timezone = ""
    with patch("core.dates.timezone.now", return_value=_at_utc(2026, 6, 1, 12, 0)):
        assert today_local(store) == date(2026, 6, 1)
