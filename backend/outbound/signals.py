"""Booking-lifecycle signals that populate the outbound queue.

Filled in by task #116. This module is imported by `OutboundConfig.ready()`
so it must exist from the migration task onward; the actual signal handlers
land with the signals task.
"""

from __future__ import annotations
