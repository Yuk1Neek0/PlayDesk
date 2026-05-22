"""
Lightweight language detection for the bilingual front-desk agent.

PlayDesk serves an EN / 中 user base, so detection only needs to tell those
two apart — a scan for CJK ideographs is sufficient and dependency-free.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES = ("en", "zh")


def detect_language(text: str) -> str:
    """
    Return the ISO-639-1 code of *text*'s language.

    "zh" when the text contains any CJK Unified Ideograph, otherwise "en".
    A single Chinese character is enough — booking messages often mix a
    Chinese sentence with a Latin name or phone number.
    """
    for ch in text:
        if "一" <= ch <= "鿿":  # CJK Unified Ideographs block
            return "zh"
    return "en"
