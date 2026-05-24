"""Backfill `check_in_token` for every existing booking.

Idempotent: only fills rows whose `check_in_token` is NULL or empty.
Re-running the migration after the column is fully populated is a
no-op. Token generation is duplicated locally (rather than imported
from `core.tokens`) so the migration stays self-contained.
"""

import secrets

from django.db import migrations

_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_LENGTH = 8


def _generate(existing: set[str]) -> str:
    """Return a token that is not already in ``existing``."""
    # 32**8 ≈ 1.1e12 keyspace — collisions on a 10k-row backfill are
    # vanishingly unlikely; retry a few times defensively just in case.
    for _ in range(5):
        token = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
        if token not in existing:
            return token
    raise RuntimeError("Unable to mint unique check_in_token after retries.")


def forward(apps, schema_editor):
    Booking = apps.get_model("core", "Booking")
    # Pull the already-populated tokens into memory so we can dedupe
    # against them as we mint. The set is per-process and we ship the
    # final assignment via .save() so the unique index catches any
    # accidental dup at write time too.
    existing = set(
        Booking.objects.exclude(check_in_token__isnull=True)
        .exclude(check_in_token="")
        .values_list("check_in_token", flat=True)
    )
    qs = Booking.objects.filter(check_in_token__isnull=True) | Booking.objects.filter(
        check_in_token=""
    )
    for booking in qs.distinct():
        token = _generate(existing)
        existing.add(token)
        booking.check_in_token = token
        booking.save(update_fields=["check_in_token"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_booking_check_in_fields"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
