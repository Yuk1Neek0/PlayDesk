"""
Customer resolution for booking creation.

A single seam used by `agent_tools.create_booking` and the REST
`BookingCreateSerializer`: given a raw name + phone pair coming in from
either path, return the canonical `Customer` row to attach to the new
`Booking`. New customers are created opportunistically; existing
customers' blank fields are filled in if the new booking has better
data (e.g. a name was missing before).
"""

from __future__ import annotations

from django.db import transaction

from .models import Customer, Store
from .phone import normalize_phone


class UnparseablePhoneError(ValueError):
    """Raised when the supplied phone cannot be normalised to E.164."""


@transaction.atomic
def resolve_customer(
    *,
    store: Store,
    raw_phone: str,
    name: str = "",
    locale_pref: str | None = None,
) -> Customer:
    """Find or create a `Customer` for (store, normalised phone).

    Raises ``UnparseablePhoneError`` if the phone cannot be turned into
    E.164 — callers translate that into a 400 / structured tool error.

    If the customer already exists, this updates blank ``name`` /
    ``locale_pref`` fields with the new values (so a sparse legacy
    record gets enriched as we learn more), but never overwrites a
    non-empty existing value.
    """
    normalized = normalize_phone(raw_phone)
    if not normalized:
        raise UnparseablePhoneError(f"Could not parse phone number: {raw_phone!r}")

    customer, created = Customer.objects.get_or_create(
        store=store,
        phone=normalized,
        defaults={
            "name": name or "",
            "locale_pref": locale_pref or "en",
        },
    )

    if not created:
        dirty = False
        if name and not customer.name:
            customer.name = name
            dirty = True
        if locale_pref and customer.locale_pref == "en" and locale_pref != "en":
            # Only override the default ('en') — never override an explicit choice.
            customer.locale_pref = locale_pref
            dirty = True
        if dirty:
            customer.save(update_fields=["name", "locale_pref"])

    return customer
