"""Rotating in-store check-in QR keys (v11a).

One row = one short-lived (~15 min) rotating key bound to a single
store. The customer-facing `/c-in/?k=<key>` page resolves the key,
opens an OTP flow, then auto/manual-checks the customer into one of
their same-day-window bookings.

The model is intentionally thin — the rotation engine + resolver live
in `checkin.services`. The `superseded_at` column gives the previous
key a configurable grace window so customers who scanned mid-rotation
don't see a flash-410.
"""

from __future__ import annotations

from django.db import models

from core.models import Store


class RotatingCheckinKey(models.Model):
    """A single 10-char rotating key for a store's door QR.

    `key` is base32-alike using a no-ambiguous alphabet so customers
    can read it off a printed sign in a pinch. `expires_at` is set at
    mint time from the store's `checkin_rotation_minutes`. `superseded_at`
    is filled in by `mint_key(...)` when this key is replaced by a
    fresher one — the resolver still accepts it for `grace_seconds`
    afterwards so a scan during the swap-over keeps working.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="checkin_keys")
    key = models.CharField(max_length=16, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "expires_at"], name="rck_store_expires_idx"),
            models.Index(fields=["store", "superseded_at"], name="rck_store_superseded_idx"),
        ]

    def __str__(self) -> str:
        return f"RotatingCheckinKey {self.key} store={self.store_id}"
