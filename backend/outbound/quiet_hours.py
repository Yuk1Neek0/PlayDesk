"""Quiet-hours math.

`next_send_time(scheduled, store, urgent=False)` returns:
- `scheduled` unchanged if `urgent=True` (urgent templates bypass).
- `scheduled` unchanged if the local time at `scheduled` is OUTSIDE the
  store's quiet window.
- Otherwise the next instant where local time equals `store.quiet_hours_end`
  (the first allowed moment after the window).

The quiet window wraps around midnight when `start > end` (the default
22:00 → 08:00 case). A degenerate `start == end` is treated as "no
quiet hours" — sending is always allowed.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.models import Store


def _in_quiet_window(local_t: time, start: time, end: time) -> bool:
    """Is `local_t` inside the quiet window `[start, end)`?

    Handles the midnight-wrap case (`start > end`, e.g. 22:00 → 08:00).
    """
    if start == end:
        return False  # Degenerate: never quiet.
    if start < end:
        # Same-day window, e.g. 02:00 → 05:00.
        return start <= local_t < end
    # Wraps midnight.
    return local_t >= start or local_t < end


def next_send_time(scheduled: datetime, store: Store, urgent: bool = False) -> datetime:
    """Compute the first allowed send time at-or-after `scheduled`.

    `scheduled` must be timezone-aware (it always is — Django uses TZ-aware
    datetimes when `USE_TZ=True`, which the project requires).
    """
    if urgent:
        return scheduled

    start = store.quiet_hours_start
    end = store.quiet_hours_end
    if start == end:
        return scheduled

    tz = ZoneInfo(store.timezone or "UTC")
    local = scheduled.astimezone(tz)
    if not _in_quiet_window(local.timetz().replace(tzinfo=None), start, end):
        return scheduled

    # Inside the window — jump forward to today's (or tomorrow's) `end`.
    candidate = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(scheduled.tzinfo)
