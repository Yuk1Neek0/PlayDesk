"""
Data migration: backfill Booking.customer from legacy customer_phone.

Idempotent — walks every booking whose `customer_id` is null, normalises
its `customer_phone`, and links it to the find-or-created Customer for
(booking.resource.store, normalised phone). Bookings with unparseable
phones stay unlinked and surface in the next run if their data improves.

The legacy `customer_name` / `customer_phone` columns remain in place
for one release cycle so anything still reading them keeps working.
"""

from __future__ import annotations

from django.db import migrations


def backfill_customers(apps, schema_editor):
    Booking = apps.get_model("core", "Booking")
    Customer = apps.get_model("core", "Customer")

    # `apps.get_model` returns the historical model — we can't use the
    # live `core.customers.resolve_customer()` helper here because it
    # imports the live model. Phone normalisation has no such constraint.
    from core.phone import normalize_phone

    for booking in Booking.objects.select_related("resource__store").filter(customer__isnull=True):
        raw = booking.customer_phone
        normalized = normalize_phone(raw)
        if not normalized:
            # Skip unparseable rows — they stay legacy-only.
            continue
        store = booking.resource.store
        customer, _created = Customer.objects.get_or_create(
            store_id=store.id,
            phone=normalized,
            defaults={"name": booking.customer_name or "", "locale_pref": "en"},
        )
        if not customer.name and booking.customer_name:
            customer.name = booking.customer_name
            customer.save(update_fields=["name"])
        booking.customer = customer
        booking.customer_phone = normalized
        booking.save(update_fields=["customer", "customer_phone"])


def noop_reverse(apps, schema_editor):
    """Reverse migration unlinks Booking.customer but leaves Customer rows."""
    Booking = apps.get_model("core", "Booking")
    Booking.objects.update(customer=None)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_customer_and_note"),
    ]

    operations = [
        migrations.RunPython(backfill_customers, reverse_code=noop_reverse),
    ]
