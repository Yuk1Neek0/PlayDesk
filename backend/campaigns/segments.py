"""
Segment evaluator: compiles a `Segment.filter` JSON DSL into a Django ORM
queryset over `Customer`. Always store-scoped by construction; unknown DSL
keys are logged and ignored (forward-compat).

DSL keys (all optional, ANDed together):
  tags_include: list[str]          -> tags JSON-contains every listed tag
  min_total_visits: int            -> total_visits >= N
  last_visit_within_days: int      -> last_visit_at >= now() - N days
  locale_pref: 'en' | 'zh'         -> locale_pref = ...
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import QuerySet
from django.utils import timezone

from core.models import Customer

from .models import Segment

logger = logging.getLogger(__name__)

KNOWN_KEYS = frozenset(
    {
        "tags_include",
        "min_total_visits",
        "last_visit_within_days",
        "locale_pref",
    }
)


def customers_for(segment: Segment) -> QuerySet[Customer]:
    """Return the customers matched by `segment`'s DSL filter.

    The store filter is the first chain link — no caller can opt out of it.
    Predicates are composed server-side; no Python-level filtering.
    """
    qs = Customer.objects.filter(store=segment.store)
    filt = segment.filter or {}

    for key in filt:
        if key not in KNOWN_KEYS:
            logger.warning("[campaigns] unknown segment key: %s", key)

    tags = filt.get("tags_include")
    if tags:
        for tag in tags:
            qs = qs.filter(tags__contains=[tag])

    min_visits = filt.get("min_total_visits")
    if min_visits is not None:
        qs = qs.filter(total_visits__gte=int(min_visits))

    days = filt.get("last_visit_within_days")
    if days is not None:
        days_int = int(days)
        if days_int == 0:
            # Boundary semantic: 0 means "today's visitors" — anything since
            # the start of the current UTC day. A literal `now() - 0 days`
            # would be a moving target as the query is evaluated.
            now = timezone.now()
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            cutoff = timezone.now() - timedelta(days=days_int)
        qs = qs.filter(last_visit_at__gte=cutoff)

    locale = filt.get("locale_pref")
    if locale:
        qs = qs.filter(locale_pref=locale)

    return qs
