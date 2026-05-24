"""Rotate the door-QR rotating key for every store that needs it.

Designed for `* * * * * python manage.py rotate_checkin_keys` cron —
runs every minute, idempotent. For each store, if the most recent key
is older than `store.checkin_rotation_minutes - 1` minutes (one-minute
slop so cron drift doesn't miss a rotation), mint a fresh key. The
previous key gets `superseded_at = now()` inside `mint_key` so a scan
during the swap-over still resolves for ~60s.

Options:
  --force           Mint regardless of age.
  --store SLUG      Only operate on the named store.
  --dry-run         Log what would happen but don't write.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Store

from ...services import get_active_key, mint_key


class Command(BaseCommand):
    help = "Rotate the in-store check-in QR key for each store."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--force", action="store_true", help="Always mint, ignoring age.")
        parser.add_argument(
            "--store",
            default=None,
            help="Restrict to this store slug. Default: all stores.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen but don't write.",
        )

    def handle(self, *args, **options) -> None:
        stores = Store.objects.all()
        if options["store"]:
            stores = stores.filter(slug=options["store"])

        now = timezone.now()
        for store in stores:
            minutes = max(1, int(getattr(store, "checkin_rotation_minutes", 15)))
            active = get_active_key(store)
            # Mint when forced, when there's no active key at all, or when
            # the active key is older than the rotation interval (with 1
            # minute of slop to keep cron drift safe).
            needs_rotation = (
                options["force"]
                or active is None
                or active.created_at < now - timedelta(minutes=max(1, minutes - 1))
            )
            if not needs_rotation:
                self.stdout.write(f"  {store.slug}: fresh — key {active.key}")
                continue
            if options["dry_run"]:
                self.stdout.write(f"  {store.slug}: WOULD mint (dry-run)")
                continue
            new_key = mint_key(store)
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {store.slug}: minted {new_key.key} expires={new_key.expires_at:%H:%M:%S}"
                )
            )
