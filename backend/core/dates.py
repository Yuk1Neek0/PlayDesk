"""Date helpers that respect a Store's local timezone.

The v3 timezone fixes established that all display-side time math runs in
store-local time. The business-dashboard slice needs the same for its
day-window aggregates, so the helper lives here in one place rather than
being re-derived in every view.
"""

from __future__ import annotations

import logging
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

logger = logging.getLogger(__name__)


def today_local(store) -> date:
    """Return today's date in ``store.timezone``.

    Falls back to UTC and logs a warning when the store's timezone is
    empty, malformed, or unknown to ``zoneinfo`` — the business-metrics
    endpoint should not 500 because of a single misconfigured store.
    """
    tz_name = getattr(store, "timezone", "") or ""
    try:
        tz = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(
            "today_local: store %s has invalid timezone %r; falling back to UTC",
            getattr(store, "pk", "?"),
            tz_name,
        )
        tz = ZoneInfo("UTC")
    return timezone.now().astimezone(tz).date()
