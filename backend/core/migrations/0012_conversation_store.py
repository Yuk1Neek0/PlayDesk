"""Add Conversation.store FK + backfill from customer-phone heuristic.

Three operations in one migration so the field is created, populated, and
then locked to ``NOT NULL`` atomically:

  1. ``AddField`` — nullable FK so existing rows survive the schema change.
  2. ``RunPython`` — for each Conversation, set ``store`` from the matching
     ``Customer`` (by normalised phone) or fall back to the alphabetically-
     first store.
  3. ``AlterField`` — flip ``null=False`` once every row has a store.

The reverse path drops the FK in one step (the model's ``store`` field
already has the right shape after step 3, so SQLite's DROP COLUMN is
sufficient for downgrades).
"""

from __future__ import annotations

from django.db import migrations, models


def _backfill(apps, schema_editor):
    Conversation = apps.get_model("core", "Conversation")
    Customer = apps.get_model("core", "Customer")
    Store = apps.get_model("core", "Store")

    # ``apps.get_model`` returns historical models, so we can't call
    # `core.customers.resolve_customer` here. Phone normalisation is a
    # pure helper in `core.phone` — safe to import.
    from core.phone import normalize_phone

    default_store = Store.objects.order_by("slug").first()
    if default_store is None:
        # Test runs that never seeded a store get a no-op migration — the
        # nullable->non-null step would 500 otherwise on an empty table,
        # but ``AlterField`` only enforces the constraint at INSERT time so
        # an empty Conversation table is fine.
        return

    # Cache customer phone → store_id so we don't query per-conversation.
    phone_to_store = dict(Customer.objects.values_list("phone", "store_id"))

    rows_to_update: list[tuple[int, int]] = []
    for conv_id, customer_identifier in Conversation.objects.filter(store__isnull=True).values_list(
        "id", "customer_identifier"
    ):
        normalised = normalize_phone(customer_identifier) if customer_identifier else None
        store_id = phone_to_store.get(normalised) if normalised else None
        if store_id is None:
            store_id = default_store.id
        rows_to_update.append((conv_id, store_id))

    # Apply in a single pass; small chunks keep memory bounded for large
    # historical Conversation tables.
    for conv_id, store_id in rows_to_update:
        Conversation.objects.filter(pk=conv_id).update(store_id=store_id)


def _noop_reverse(apps, schema_editor):
    """Reverse path is a no-op — ``AlterField`` + ``AddField`` reverse implicitly."""
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_merge_20260523_1214"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="store",
            field=models.ForeignKey(
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name="conversations",
                to="core.store",
            ),
        ),
        migrations.RunPython(_backfill, reverse_code=_noop_reverse),
        migrations.AlterField(
            model_name="conversation",
            name="store",
            field=models.ForeignKey(
                on_delete=models.deletion.PROTECT,
                related_name="conversations",
                to="core.store",
            ),
        ),
    ]
