"""Shared OTP request/verify primitives for v7 customer-portal AND v11a
rotating-checkin.

The two surfaces (`/api/customer-auth/...` and `/api/c-in/...`) share
the same OTP infrastructure: same `CustomerOTP` table, same rate
limits, same `attempts` cap, same SMS adapter. This module owns the
business logic so neither view layer has to duplicate it.

Public functions:

  - `do_request_code(phone, store, *, test_mode=False)`
      Returns `(otp_row, error)` where `error` is None on success or
      one of `"rate_limit_minute"`, `"rate_limit_hour"`. Caller maps to
      HTTP 201 / 429.

  - `do_verify_code(phone, code, store, *, ip="")`
      Returns `("ok", otp)` on success, `("invalid", None)` on a wrong
      code / expired code / unknown phone (use 401), or
      `("too_many_attempts", None)` after the attempt cap (use 429).
      `customer` is optional — v11a doesn't need it because identity
      is "anyone holding this phone", not "a registered Customer row".

  - `mark_otp_used(otp)` — explicit consume helper.

The "no consume on verify-and-find" pattern used by v11a is the
reason `do_verify_code` doesn't auto-consume — the v7 view consumes
inline, v11a relies on `mark_otp_used` after the check-in flips.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import CustomerLoginAttempt, CustomerOTP, Store

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
RATE_LIMIT_PER_MINUTE = 1
RATE_LIMIT_PER_HOUR = 5


def generate_otp_code() -> str:
    """Six random digits via `secrets.choice` — auth-grade unpredictability."""
    return "".join(secrets.choice("0123456789") for _ in range(6))


def _rate_check(store: Store, phone: str) -> str | None:
    """Per-(store, phone) rate limit. Returns an error sentinel or None.

    Identical rules to v7: 1 request per 60s, 5 per hour. Sharing this
    function means a rotating-checkin OTP shares the bucket with a
    customer-portal OTP for the same phone — by design (an attacker
    can't bypass v7's cap by hopping to v11a).
    """
    key_minute = f"otp:req:{store.id}:{phone}:1m"
    key_hour = f"otp:req:{store.id}:{phone}:1h"
    if not cache.add(key_minute, 1, timeout=60):
        return "rate_limit_minute"
    hour_count = cache.get(key_hour, 0)
    if hour_count >= RATE_LIMIT_PER_HOUR:
        return "rate_limit_hour"
    cache.set(key_hour, hour_count + 1, timeout=3600)
    return None


def do_request_code(
    phone: str,
    store: Store,
    *,
    test_mode: bool = False,
) -> tuple[CustomerOTP | None, str | None]:
    """Mint a fresh OTP for `(phone, store)`. Returns `(otp, error)`.

    On success: invalidates any prior un-used OTP, creates a new row,
    sends via the SMS adapter (adapter failures are logged but the row
    is still returned — operator can resend). `test_mode` bypasses
    rate limits and is DEBUG-gated by the caller.

    On rate limit: returns `(None, "rate_limit_minute" | "rate_limit_hour")`.
    """
    if not test_mode:
        err = _rate_check(store, phone)
        if err is not None:
            return None, err

    # Invalidate any prior un-used OTP for this phone+store.
    CustomerOTP.objects.filter(phone=phone, store=store, used_at__isnull=True).update(
        used_at=timezone.now()
    )

    otp = CustomerOTP.objects.create(
        phone=phone,
        store=store,
        code=generate_otp_code(),
        expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
    )

    body = f"Your PlayDesk verification code: {otp.code}. Expires in 10 minutes."
    try:
        from agent.channels.registry import get_outbound_adapter

        adapter = get_outbound_adapter("sms")
        adapter.send(phone, body)
    except Exception:
        # Adapter failure is non-fatal — the row exists, an operator can resend.
        import logging

        logging.getLogger(__name__).exception(
            "OTP send failed for phone=%s store=%s otp=%s", phone, store.slug, otp.id
        )

    return otp, None


def do_verify_code(
    phone: str,
    code: str,
    store: Store,
    *,
    ip: str = "",
) -> tuple[str, CustomerOTP | None]:
    """Verify the latest non-used, non-expired OTP for `(phone, store)`.

    Returns one of:
      ``("ok", otp_row)``           — code matched, row is NOT auto-consumed
      ``("invalid", None)``         — wrong code, expired, or unknown phone
      ``("too_many_attempts", None)`` — attempts on this OTP went over cap

    Always writes a `CustomerLoginAttempt` row regardless of outcome
    so the audit log is complete. The caller decides whether to consume
    the OTP (v7 does it inline; v11a defers to the check-in step).
    """
    otp = (
        CustomerOTP.objects.filter(phone=phone, store=store, used_at__isnull=True)
        .order_by("-created_at", "-id")
        .first()
    )

    def _fail(kind: str) -> tuple[str, CustomerOTP | None]:
        CustomerLoginAttempt.objects.create(phone=phone, store=store, success=False, ip_address=ip)
        return kind, None

    if otp is None:
        return _fail("invalid")

    otp.attempts += 1
    if otp.attempts > OTP_MAX_ATTEMPTS:
        otp.used_at = timezone.now()
        otp.save(update_fields=["attempts", "used_at"])
        return _fail("too_many_attempts")
    otp.save(update_fields=["attempts"])

    if otp.expires_at < timezone.now():
        return _fail("invalid")
    if otp.code != code:
        return _fail("invalid")

    CustomerLoginAttempt.objects.create(phone=phone, store=store, success=True, ip_address=ip)
    return "ok", otp


def mark_otp_used(otp: CustomerOTP) -> None:
    """Explicit `used_at = now()` so re-verification fails."""
    otp.used_at = timezone.now()
    otp.save(update_fields=["used_at"])
