"""Token generation helpers.

`check_in_token` is a short, human-readable, base32-style identifier
embedded in the customer's booking-confirmation SMS as `/c/<token>`.
The alphabet deliberately excludes the visually-ambiguous characters
(`0`, `O`, `1`, `I`, `l`) so a customer can read the token off a
printed sign without typos.

These tokens are URL credentials — anyone with a token can check the
booking in — so we use :func:`secrets.choice` (not `random.choice`).
The keyspace is 32**8 = 1.1 * 10**12, which is well past brute-force
threat at PlayDesk request volume.
"""

from __future__ import annotations

import secrets

# 32 chars: full base32 minus the ambiguous five (0, O, 1, I, l).
CHECK_IN_TOKEN_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CHECK_IN_TOKEN_LENGTH = 8


def generate_check_in_token() -> str:
    """Return a fresh 8-char token sampled from :data:`CHECK_IN_TOKEN_ALPHABET`.

    Does NOT check the DB for uniqueness — use
    :func:`generate_unique_check_in_token` for that. Pure-function so it
    can be called from migrations without importing the model.
    """
    return "".join(secrets.choice(CHECK_IN_TOKEN_ALPHABET) for _ in range(CHECK_IN_TOKEN_LENGTH))


def generate_unique_check_in_token(max_retries: int = 5) -> str:
    """Return a token guaranteed not to collide with an existing Booking.

    Retries up to ``max_retries`` times — collisions at this keyspace
    are vanishingly unlikely so retry exhaustion almost certainly
    indicates a bug (e.g. seeded fixture forcing duplicates). Imported
    lazily to keep the module importable from migrations.
    """
    # Import inside the function so this module stays safe to import
    # from a data migration (which already has an `apps` registry but
    # not necessarily the live Booking model loaded).
    from core.models import Booking

    for _ in range(max_retries):
        token = generate_check_in_token()
        if not Booking.objects.filter(check_in_token=token).exists():
            return token
    raise RuntimeError(f"Unable to generate unique check-in token after {max_retries} attempts.")
