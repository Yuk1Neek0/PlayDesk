"""Tests for agent.language.detect_language (Issue #27)."""

from __future__ import annotations

from agent.language import detect_language


def test_detects_english():
    assert detect_language("Is the PS5 free on Saturday at 8pm?") == "en"


def test_detects_chinese():
    assert detect_language("请问周六晚上8点PS5有空吗？") == "zh"


def test_mixed_text_with_any_cjk_is_chinese():
    # Booking messages often mix a Chinese sentence with a Latin name / phone.
    assert detect_language("预订 PS5 A台，王芳 13800000002") == "zh"


def test_empty_string_defaults_to_english():
    assert detect_language("") == "en"


def test_digits_and_punctuation_are_english():
    assert detect_language("+86-138-0000-0001") == "en"
