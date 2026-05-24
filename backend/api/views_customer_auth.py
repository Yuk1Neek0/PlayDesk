"""Customer-portal auth endpoints — phone + SMS OTP.

Three endpoints, all unauthenticated at the API layer (the customer
isn't logged in yet by definition):

  - POST /api/customer-auth/request-code/  — send a fresh 6-digit OTP.
  - POST /api/customer-auth/verify-code/   — exchange code for cookie.
  - POST /api/customer-auth/logout/        — clear the cookie.

The verify-code endpoint sets the signed `pd_customer_session` cookie
via `core.middleware.sign_customer_session` so subsequent requests
authenticate through `CustomerSessionMiddleware` setting
`request.customer`.

Rate limits via Django cache:
  - request-code: 1 per phone per 60s + 5 per phone per hour.
  - verify-code: 5 attempts per OTP row, then invalidate.

Phone-existence is never leaked: an unknown phone still records a
`CustomerLoginAttempt(success=False)` and returns 401, matching the
behaviour for a known phone with the wrong code.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.middleware import (
    CUSTOMER_COOKIE_MAX_AGE,
    CUSTOMER_COOKIE_NAME,
    sign_customer_session,
)
from core.models import Customer, CustomerLoginAttempt, CustomerOTP, Store

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
RATE_LIMIT_PER_MINUTE = 1
RATE_LIMIT_PER_HOUR = 5


def _generate_code() -> str:
    """Six random digits — secrets.choice keeps them auth-grade unpredictable."""
    return "".join(secrets.choice("0123456789") for _ in range(6))


def _client_ip(request) -> str:
    """Best-effort client IP for the audit log. Trims to model max_length."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()[:64]
    return (request.META.get("REMOTE_ADDR") or "")[:64]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class RequestCodeSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32)
    store_slug = serializers.CharField(max_length=64)


class VerifyCodeSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=32)
    code = serializers.CharField(max_length=6)
    store_slug = serializers.CharField(max_length=64)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class RequestCodeView(APIView):
    """POST /api/customer-auth/request-code/

    Generates a fresh OTP for `(phone, store)`. Invalidates any prior
    code so only the latest one verifies. Sends via the registered SMS
    outbound adapter — failures are silent (the row is created so an
    operator can resend manually) to avoid leaking adapter state.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        ser = RequestCodeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = ser.validated_data["phone"].strip()
        slug = ser.validated_data["store_slug"].strip()

        try:
            store = Store.objects.get(slug=slug)
        except Store.DoesNotExist:
            return Response({"detail": "Unknown store."}, status=status.HTTP_404_NOT_FOUND)

        # Per-phone+store rate limits. cache.add returns False when the
        # key already exists, so the first request seeds it and a second
        # within the window bounces.
        key_minute = f"otp:req:{store.id}:{phone}:1m"
        key_hour = f"otp:req:{store.id}:{phone}:1h"
        if not cache.add(key_minute, 1, timeout=60):
            return Response(
                {"detail": "Too many requests. Please wait 60 seconds."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        # Hourly count via incr — defaults to 1 on first call.
        hour_count = cache.get(key_hour, 0)
        if hour_count >= RATE_LIMIT_PER_HOUR:
            return Response(
                {"detail": "Too many requests. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        cache.set(key_hour, hour_count + 1, timeout=3600)

        # Invalidate any prior un-used OTP for this phone+store.
        CustomerOTP.objects.filter(phone=phone, store=store, used_at__isnull=True).update(
            used_at=timezone.now()
        )

        otp = CustomerOTP.objects.create(
            phone=phone,
            store=store,
            code=_generate_code(),
            expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
        )

        # Send via the SMS outbound adapter directly — there's no
        # Customer row to drive `enqueue_message` (the phone may not be
        # registered yet, and we never want to leak that signal).
        body = f"Your PlayDesk verification code: {otp.code}. Expires in 10 minutes."
        try:
            from agent.channels.registry import get_outbound_adapter

            adapter = get_outbound_adapter("sms")
            adapter.send(phone, body)
        except Exception:
            # Adapter failure is non-fatal for the request flow — the OTP
            # row exists. Operator can resend or check provider config.
            import logging

            logging.getLogger(__name__).exception(
                "OTP send failed for phone=%s store=%s otp=%s", phone, slug, otp.id
            )

        payload = {"request_id": otp.id}
        # Test-mode hatch: surface the code so e2e tests can complete the
        # flow without a real SMS sink. Gated on DEBUG so production
        # never leaks the code regardless of query params.
        if settings.DEBUG and (
            request.query_params.get("test_mode") or request.GET.get("test_mode")
        ):
            payload["code"] = otp.code
        return Response(payload, status=status.HTTP_201_CREATED)


class VerifyCodeView(APIView):
    """POST /api/customer-auth/verify-code/

    Validates the latest non-used, non-expired OTP for `(phone, store)`.
    On success: 200 with `{customer: {id, name}}` and a signed cookie.
    On failure: 401 (phone unknown, code wrong, code expired). The
    audit log records every attempt regardless of outcome.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        ser = VerifyCodeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = ser.validated_data["phone"].strip()
        code = ser.validated_data["code"].strip()
        slug = ser.validated_data["store_slug"].strip()
        ip = _client_ip(request)

        try:
            store = Store.objects.get(slug=slug)
        except Store.DoesNotExist:
            return Response({"detail": "Unknown store."}, status=status.HTTP_404_NOT_FOUND)

        otp = (
            CustomerOTP.objects.filter(phone=phone, store=store, used_at__isnull=True)
            .order_by("-created_at", "-id")
            .first()
        )

        def _fail(http_status: int = status.HTTP_401_UNAUTHORIZED) -> Response:
            CustomerLoginAttempt.objects.create(
                phone=phone, store=store, success=False, ip_address=ip
            )
            return Response({"detail": "Invalid code or phone."}, status=http_status)

        if otp is None:
            return _fail()

        # Bump attempts up-front; >5 invalidates the row.
        otp.attempts += 1
        if otp.attempts > OTP_MAX_ATTEMPTS:
            otp.used_at = timezone.now()
            otp.save(update_fields=["attempts", "used_at"])
            return _fail(http_status=status.HTTP_429_TOO_MANY_REQUESTS)
        otp.save(update_fields=["attempts"])

        if otp.expires_at < timezone.now():
            return _fail()
        if otp.code != code:
            return _fail()

        # Code matches — look up the customer. Unknown phone => 401 with
        # success=False audit row, so the response can't be used to
        # enumerate registered phones.
        customer = Customer.objects.filter(phone=phone, store=store).first()
        if customer is None:
            return _fail()

        # Mark the OTP used so it can't be replayed.
        otp.used_at = timezone.now()
        otp.save(update_fields=["used_at"])

        CustomerLoginAttempt.objects.create(phone=phone, store=store, success=True, ip_address=ip)

        token = sign_customer_session(customer.id, store.id)
        resp = Response(
            {"customer": {"id": customer.id, "name": customer.name}},
            status=status.HTTP_200_OK,
        )
        # Secure=False in DEBUG so e2e (HTTP localhost) can read the
        # cookie; production runs over HTTPS where Secure=True is set
        # by the reverse proxy / settings override.
        resp.set_cookie(
            CUSTOMER_COOKIE_NAME,
            token,
            max_age=CUSTOMER_COOKIE_MAX_AGE,
            httponly=True,
            secure=not settings.DEBUG,
            samesite="Lax",
            path="/",
        )
        return resp


class LogoutView(APIView):
    """POST /api/customer-auth/logout/ — clear the session cookie."""

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        resp = Response({"ok": True}, status=status.HTTP_200_OK)
        resp.delete_cookie(CUSTOMER_COOKIE_NAME, path="/")
        return resp
