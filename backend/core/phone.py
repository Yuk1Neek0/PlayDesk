"""
Phone-number normalisation.

A single source of truth used by `agent_tools.create_booking`, the REST
booking endpoint, and (cross-slice) the Twilio SMS channel adapter. Two
code paths must NEVER disagree on what "the same phone" means — anything
that compares or dedups by phone goes through `normalize_phone`.
"""

from __future__ import annotations

import phonenumbers


def normalize_phone(raw: str | None, country: str = "CA") -> str | None:
    """Return an E.164 string (e.g. ``+14165550188``) or ``None`` if unparseable.

    ``country`` is the default region for parsing local-format numbers. The
    Toronto demo store is in Canada; staging environments in other regions
    pass their own ISO 3166-1 alpha-2 country code.

    The function is idempotent: re-normalising an already-E.164 string
    yields the same string. Whitespace, dashes, and parentheses are
    tolerated. Empty / None / unparseable inputs return ``None`` rather
    than raising — callers decide whether that is fatal.
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = phonenumbers.parse(raw, country)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
