"""Tests for the phone-normalisation helper."""

from __future__ import annotations

import pytest

from core.phone import normalize_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+1 (416) 555-0188", "+14165550188"),
        ("416-555-0188", "+14165550188"),
        ("4165550188", "+14165550188"),
        ("+1 416 555 0188", "+14165550188"),
        ("  +14165550188  ", "+14165550188"),
    ],
)
def test_normalizes_various_canadian_formats(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", None, "garbage", "+1", "12", "abcdefghij"],
)
def test_returns_none_on_unparseable(raw: str | None) -> None:
    assert normalize_phone(raw) is None


def test_is_idempotent() -> None:
    once = normalize_phone("+1 (416) 555-0188")
    twice = normalize_phone(once)
    assert once == twice == "+14165550188"


def test_respects_country_default() -> None:
    # An eight-digit Shanghai mobile becomes E.164 only when CN is the
    # default. With the default 'CA', it's unparseable.
    assert normalize_phone("13800138000", country="CN") == "+8613800138000"
    assert normalize_phone("13800138000", country="CA") is None
