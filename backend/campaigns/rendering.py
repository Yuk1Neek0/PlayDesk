"""
Body-template rendering for campaigns.

Mirrors the `SafeFormatter` pattern used by outbound's templates: dotted
attribute access on context objects, missing keys raise a clear KeyError
at send time (never silently produce empty strings in production).
"""

from __future__ import annotations

import string
from typing import Any


class SafeFormatter(string.Formatter):
    """A `str.Formatter` that fetches dotted attribute paths against the
    provided context dict and raises a clear KeyError on missing keys."""

    def get_field(self, field_name: str, args, kwargs):
        first, _, rest = field_name.partition(".")
        try:
            obj: Any = kwargs[first]
        except KeyError as exc:
            raise KeyError(f"Unknown template variable: {first!r}") from exc

        for part in rest.split(".") if rest else []:
            try:
                obj = getattr(obj, part)
            except AttributeError as exc:
                raise KeyError(f"Missing attribute {part!r} on {first!r} in template") from exc
        return obj, first


def render(template: str, context: dict[str, Any]) -> str:
    """Render `template` with `context` (str → str). Raises KeyError on a
    missing variable so a malformed body fails loud at send time, not
    silently in production."""
    return SafeFormatter().vformat(template, (), context)
