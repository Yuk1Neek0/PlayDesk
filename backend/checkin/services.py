"""Rotation engine + resolver for `RotatingCheckinKey`.

Three public functions:

  - `mint_key(store)` — atomically supersede the previous active key
    and create a fresh one. Returns the new row.
  - `get_active_key(store)` — read-only helper used by the admin
    settings page + display surface.
  - `resolve_key(key_str)` — public-side lookup. Returns the row when
    the key is current OR within the grace window; None otherwise.

The token alphabet excludes ambiguous characters (`0/O/1/I/l`) because
customers may read the key off a printed sign.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import RotatingCheckinKey

# 32-char base32-ish alphabet — no 0/O/1/I/L.
KEY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
KEY_LENGTH = 10
# Default grace: a scan within this many seconds of a rotation still
# resolves the old key. Cron rotates every minute so 60s is safe.
DEFAULT_GRACE_SECONDS = 60


def _generate_key() -> str:
    """10-char key from the no-ambiguous alphabet via `secrets.choice`.

    Caller retries on UNIQUE collision (vanishingly rare at 32^10).
    """

    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_LENGTH))


@transaction.atomic
def mint_key(store) -> RotatingCheckinKey:
    """Create a fresh rotating key for `store`; supersede the previous one.

    Runs inside a transaction so the supersede + create can't tear. The
    previous key keeps working for `DEFAULT_GRACE_SECONDS` so customers
    mid-scan don't see a 410.
    """

    now = timezone.now()
    minutes = max(1, int(getattr(store, "checkin_rotation_minutes", 15)))

    # Mark any not-yet-superseded keys for this store as superseded now.
    RotatingCheckinKey.objects.filter(
        store=store,
        superseded_at__isnull=True,
    ).update(superseded_at=now)

    # Retry-on-collision loop — practically never triggers.
    for _ in range(5):
        candidate = _generate_key()
        if not RotatingCheckinKey.objects.filter(key=candidate).exists():
            return RotatingCheckinKey.objects.create(
                store=store,
                key=candidate,
                expires_at=now + timedelta(minutes=minutes),
            )
    raise RuntimeError("Could not generate a unique rotating check-in key")


def get_active_key(
    store, *, grace_seconds: int = DEFAULT_GRACE_SECONDS
) -> RotatingCheckinKey | None:
    """Return the freshest non-expired, non-superseded key for `store`.

    Falls back to a recently-superseded key only if no fresh one exists
    (defensive — `mint_key` would normally create the fresh one first).
    """

    now = timezone.now()
    fresh = (
        RotatingCheckinKey.objects.filter(
            store=store,
            expires_at__gt=now,
            superseded_at__isnull=True,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if fresh is not None:
        return fresh

    grace_floor = now - timedelta(seconds=grace_seconds)
    return (
        RotatingCheckinKey.objects.filter(
            store=store,
            expires_at__gt=now,
            superseded_at__gte=grace_floor,
        )
        .order_by("-created_at", "-id")
        .first()
    )


def resolve_key(
    key_str: str | None,
    *,
    grace_seconds: int = DEFAULT_GRACE_SECONDS,
) -> RotatingCheckinKey | None:
    """Public-side key lookup. Returns the row if usable, else None.

    Accepts a key that's been superseded within `grace_seconds` so a
    mid-rotation scan doesn't dead-end. Caller is responsible for the
    410 response copy.
    """

    if not key_str:
        return None
    row = RotatingCheckinKey.objects.select_related("store").filter(key=key_str).first()
    if row is None:
        return None
    now = timezone.now()
    if row.expires_at <= now:
        return None
    if row.superseded_at is not None:
        if (now - row.superseded_at).total_seconds() > grace_seconds:
            return None
    return row
