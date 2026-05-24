"""Public /api/c-in/ endpoints — rotating-QR check-in flow (v11a).

Four endpoints, all public (no auth — the rotating key + OTP is the
credential chain):

  - POST /api/c-in/lookup-key/        validate scanned key, return store
  - POST /api/c-in/request-otp/       phone → SMS OTP (v7 reuse)
  - POST /api/c-in/verify-and-find/   OTP → matching same-day bookings
  - POST /api/c-in/check-in/          flip booking to CHECKED_IN

OTP infrastructure is 100% v7 reuse via `core.customer_auth`.
The "no consume on verify-and-find, consume on check-in" pattern means
the customer types their code once and it covers both steps. A
short-TTL cache key (`checkin_verified:<phone>`) records the
verification so the check-in endpoint doesn't need the code again.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.customer_auth import do_request_code, do_verify_code, mark_otp_used
from core.models import Booking, BookingStatus
from core.phone import normalize_phone

from .services import resolve_key

# Verification cache TTL — customer has 5 minutes between verify and check-in.
CHECKIN_VERIFIED_TTL_SECONDS = 300
# Same-day lookup window (±) — defence-in-depth on top of OTP.
BOOKING_LOOKUP_WINDOW_HOURS = 2


def _verified_cache_key(phone: str) -> str:
    return f"checkin_verified:{phone}"


def _client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()[:64]
    return (request.META.get("REMOTE_ADDR") or "")[:64]


def _normalize_or_raw(phone: str) -> str:
    """Normalise to E.164 if possible; fall back to the raw input.

    Bookings created by other paths (manual admin, agent-created) may
    have non-E.164 strings, so we don't 400 on an unparseable input —
    we let the booking lookup match whichever form was stored.
    """
    normalized = normalize_phone(phone)
    return normalized or phone.strip()


def _expired_response() -> Response:
    return Response(
        {"detail": "Code expired — please ask staff for the current QR."},
        status=status.HTTP_410_GONE,
    )


def _booking_payload(booking: Booking) -> dict:
    return {
        "id": booking.id,
        "resource_name": booking.resource.name,
        "start_time": booking.start_time.isoformat(),
        "end_time": booking.end_time.isoformat(),
        "status": booking.status,
        "checked_in_at": (booking.checked_in_at.isoformat() if booking.checked_in_at else None),
        "customer_name": booking.customer_name or "",
        "can_check_in": booking.status == BookingStatus.CONFIRMED,
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class _LookupSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=16)


class _RequestOtpSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=16)
    phone = serializers.CharField(max_length=32)


class _VerifyAndFindSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=16)
    phone = serializers.CharField(max_length=32)
    code = serializers.CharField(max_length=6)


class _CheckInSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=16)
    phone = serializers.CharField(max_length=32)
    booking_id = serializers.IntegerField()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class LookupKeyView(APIView):
    """POST /api/c-in/lookup-key/

    Resolves a scanned key to its store. Returns 200 with store data
    if usable (current or within grace window); 410 otherwise.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        ser = _LookupSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        row = resolve_key(ser.validated_data["key"].strip())
        if row is None:
            return _expired_response()
        return Response(
            {
                "store_slug": row.store.slug,
                "store_name": row.store.name,
                "expires_at": row.expires_at.isoformat(),
            }
        )


class RequestOtpView(APIView):
    """POST /api/c-in/request-otp/ — kick off the SMS OTP via v7 shared helper."""

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        ser = _RequestOtpSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        key = ser.validated_data["key"].strip()
        phone_raw = ser.validated_data["phone"].strip()

        row = resolve_key(key)
        if row is None:
            return _expired_response()

        phone = _normalize_or_raw(phone_raw)

        # DEBUG-only test_mode bypass (mirrors v7).
        from django.conf import settings as dj_settings

        test_mode = dj_settings.DEBUG and bool(
            request.query_params.get("test_mode") or request.GET.get("test_mode")
        )

        otp, err = do_request_code(phone, row.store, test_mode=test_mode)
        if err in ("rate_limit_minute", "rate_limit_hour"):
            return Response(
                {"detail": "Too many requests. Please wait a moment and try again."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        payload = {"request_id": otp.id}
        if test_mode:
            payload["code"] = otp.code
        return Response(payload, status=status.HTTP_201_CREATED)


class VerifyAndFindView(APIView):
    """POST /api/c-in/verify-and-find/ — verify OTP, return matching bookings."""

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        ser = _VerifyAndFindSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        key = ser.validated_data["key"].strip()
        phone_raw = ser.validated_data["phone"].strip()
        code = ser.validated_data["code"].strip()

        row = resolve_key(key)
        if row is None:
            return _expired_response()

        phone = _normalize_or_raw(phone_raw)
        outcome, _otp = do_verify_code(phone, code, row.store, ip=_client_ip(request))
        if outcome == "too_many_attempts":
            return Response(
                {"detail": "Too many attempts. Please request a new code."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if outcome != "ok":
            return Response(
                {"detail": "Invalid code, please try again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # OTP verified — flag the phone as verified for ~5 min so the
        # check-in step doesn't need the code again. Do NOT consume the
        # OTP here; the check-in endpoint consumes it on success so an
        # abandoned flow lets the OTP expire naturally.
        cache.set(_verified_cache_key(phone), True, timeout=CHECKIN_VERIFIED_TTL_SECONDS)

        now = timezone.now()
        window_start = now - timedelta(hours=BOOKING_LOOKUP_WINDOW_HOURS)
        window_end = now + timedelta(hours=BOOKING_LOOKUP_WINDOW_HOURS)
        bookings = (
            Booking.objects.filter(
                resource__store=row.store,
                customer_phone=phone,
                status__in=[BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN],
                start_time__gte=window_start,
                start_time__lte=window_end,
            )
            .select_related("resource")
            .order_by("start_time")
        )

        return Response(
            {
                "bookings": [_booking_payload(b) for b in bookings],
                "store_slug": row.store.slug,
                "store_name": row.store.name,
            }
        )


class CheckInView(APIView):
    """POST /api/c-in/check-in/ — flip the chosen booking to CHECKED_IN."""

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        ser = _CheckInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        key = ser.validated_data["key"].strip()
        phone_raw = ser.validated_data["phone"].strip()
        booking_id = ser.validated_data["booking_id"]

        row = resolve_key(key)
        if row is None:
            return _expired_response()

        phone = _normalize_or_raw(phone_raw)
        if not cache.get(_verified_cache_key(phone)):
            return Response(
                {"detail": "Verification expired, please re-enter your code."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        now = timezone.now()
        window_start = now - timedelta(hours=BOOKING_LOOKUP_WINDOW_HOURS)
        window_end = now + timedelta(hours=BOOKING_LOOKUP_WINDOW_HOURS)
        booking = (
            Booking.objects.select_related("resource", "resource__store")
            .filter(
                pk=booking_id,
                resource__store=row.store,
                customer_phone=phone,
                start_time__gte=window_start,
                start_time__lte=window_end,
            )
            .first()
        )
        if booking is None:
            return Response(
                {"detail": "Booking not found for this phone in the check-in window."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if booking.status == BookingStatus.CHECKED_IN:
            # Idempotent.
            return Response(_booking_payload(booking))
        if booking.status != BookingStatus.CONFIRMED:
            return Response(
                {
                    "detail": f"Cannot check in a {booking.status} booking.",
                    "status": booking.status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        booking.status = BookingStatus.CHECKED_IN
        booking.checked_in_at = now
        booking.save(update_fields=["status", "checked_in_at"])

        # Single-use verification: consume the cache flag + the OTP row
        # so the next attempt requires a fresh code. Find the most
        # recent un-used OTP for this phone+store and mark it used.
        cache.delete(_verified_cache_key(phone))
        from core.models import CustomerOTP

        otp = (
            CustomerOTP.objects.filter(phone=phone, store=row.store, used_at__isnull=True)
            .order_by("-created_at", "-id")
            .first()
        )
        if otp is not None:
            mark_otp_used(otp)

        return Response(_booking_payload(booking))
