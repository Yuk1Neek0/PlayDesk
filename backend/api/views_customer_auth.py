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

The OTP business logic lives in `core.customer_auth` so the v11a
rotating-checkin views can reuse the same rate limits, attempt cap,
and SMS adapter without duplicating it here.

Phone-existence is never leaked: an unknown phone still records a
`CustomerLoginAttempt(success=False)` and returns 401, matching the
behaviour for a known phone with the wrong code.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.customer_auth import (
    do_request_code,
    do_verify_code,
    mark_otp_used,
)
from core.middleware import (
    CUSTOMER_COOKIE_MAX_AGE,
    CUSTOMER_COOKIE_NAME,
    sign_customer_session,
)
from core.models import Customer, Store


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

        # Test-mode bypass: DEBUG-only flag for e2e tests that need to
        # capture the OTP without a real SMS sink. Bypasses rate limits
        # so the test can drive the same phone repeatedly. Production
        # cannot trigger this path because DEBUG=False.
        test_mode = settings.DEBUG and bool(
            request.query_params.get("test_mode") or request.GET.get("test_mode")
        )

        otp, err = do_request_code(phone, store, test_mode=test_mode)
        if err == "rate_limit_minute":
            return Response(
                {"detail": "Too many requests. Please wait 60 seconds."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if err == "rate_limit_hour":
            return Response(
                {"detail": "Too many requests. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        payload = {"request_id": otp.id}
        if test_mode:
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

        outcome, otp = do_verify_code(phone, code, store, ip=ip)
        if outcome == "too_many_attempts":
            return Response(
                {"detail": "Invalid code or phone."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if outcome != "ok":
            return Response(
                {"detail": "Invalid code or phone."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Code matches — look up the customer. Unknown phone => 401
        # (same as invalid code) so the response can't be used to
        # enumerate registered phones. Log the success attempt was
        # already written by do_verify_code; overwrite with a failure
        # row so the audit trail stays accurate.
        customer = Customer.objects.filter(phone=phone, store=store).first()
        if customer is None:
            from core.models import CustomerLoginAttempt

            CustomerLoginAttempt.objects.create(
                phone=phone, store=store, success=False, ip_address=ip
            )
            return Response(
                {"detail": "Invalid code or phone."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # v7 consumes inline — the cookie is the credential from now on.
        mark_otp_used(otp)

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
