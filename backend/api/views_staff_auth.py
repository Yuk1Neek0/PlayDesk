"""Staff-portal auth endpoints — Django session + username/password.

Three endpoints under ``/api/staff/``, all CSRF-exempt so the Next.js
admin frontend can call them as plain JSON without a token round-trip:

  - POST /api/staff/login/   — authenticate, write session cookie.
  - POST /api/staff/logout/  — clear session cookie. Always 200.
  - GET  /api/staff/me/      — introspection; 200 user or 401.

The login endpoint is rate-limited per-username via the Django cache
(5 attempts per 15-minute window). A successful login clears the
counter so a legitimate user isn't permanently locked out by an
earlier failed password attempt.

This file is the entire surface the frontend talks to for staff auth.
``/api/staff/me/`` is the single source of truth for "is this browser
authenticated?" — the StaffSessionProvider polls it on mount.

Customer auth (v7 phone+OTP) is parallel and untouched: it lives at
``/api/customer-auth/*`` and uses a separate signed cookie
(``pd_customer_session``) processed by ``CustomerSessionMiddleware``.
The two namespaces never overlap.
"""

from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

User = get_user_model()


class _CsrfExemptSessionAuthentication(SessionAuthentication):
    """SessionAuthentication that skips DRF's manual CSRF enforcement.

    The staff auth endpoints are deliberately CSRF-exempt at the view
    level (``@csrf_exempt``) so the SPA can POST JSON without a token
    round-trip — overriding ``enforce_csrf`` keeps DRF aligned with
    that choice. The risk surface is identical to the customer-auth
    endpoints (v7) which use the same pattern.
    """

    def enforce_csrf(self, request):  # pragma: no cover — DRF integration
        return  # intentionally no-op


# Rate-limit window: 5 attempts per username per 15 minutes. The key is
# scoped to the username (not IP) so a single attacker rotating IPs can't
# burn through one account's window from many sources.
LOGIN_RATE_LIMIT = 5
LOGIN_RATE_WINDOW_SECONDS = 15 * 60


def _rate_limit_key(username: str) -> str:
    return f"staff_login_attempts:{username}"


def _user_payload(user) -> dict:
    """Stable JSON shape for /me/ and /login/ success bodies."""
    return {
        "id": user.id,
        "username": user.username,
        "is_superuser": bool(user.is_superuser),
        "is_staff": bool(user.is_staff),
    }


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class StaffLoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=256, trim_whitespace=False)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@method_decorator(csrf_exempt, name="dispatch")
class StaffLoginView(APIView):
    """POST /api/staff/login/

    Body ``{username, password}``. On success: writes the Django session
    cookie via ``login(request, user)`` and returns the user payload.

    Failure modes:
      - 401 invalid credentials (unknown username or wrong password).
      - 403 the user exists and the password is correct but they are
        not a staff account (``is_staff=False``). Distinguishing this
        from 401 is safe because the credentials were already validated;
        we're not leaking account existence here.
      - 429 rate limit exceeded for this username.
    """

    authentication_classes: list = [_CsrfExemptSessionAuthentication]
    permission_classes: list = []

    def post(self, request):
        ser = StaffLoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        username = ser.validated_data["username"].strip()
        password = ser.validated_data["password"]

        key = _rate_limit_key(username)
        # cache.add seeds the counter on first attempt; subsequent
        # incr() bumps it. The counter resets on successful login or
        # when the TTL elapses.
        cache.add(key, 0, timeout=LOGIN_RATE_WINDOW_SECONDS)
        try:
            attempts = cache.incr(key)
        except ValueError:
            # Key vanished between add() and incr() — rare race; reseed.
            cache.set(key, 1, timeout=LOGIN_RATE_WINDOW_SECONDS)
            attempts = 1

        if attempts > LOGIN_RATE_LIMIT:
            return Response(
                {"detail": "Too many login attempts. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_staff:
            return Response(
                {"detail": "Not a staff account."},
                status=status.HTTP_403_FORBIDDEN,
            )

        login(request, user)
        # Success — clear the rate-limit counter so a legitimate user
        # who fat-fingered the password isn't held back for 15 minutes.
        cache.delete(key)
        return Response(_user_payload(user), status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name="dispatch")
class StaffLogoutView(APIView):
    """POST /api/staff/logout/

    Always 200. Logging out an already-anonymous request is a no-op.
    """

    authentication_classes: list = [_CsrfExemptSessionAuthentication]
    permission_classes: list = []

    def post(self, request):
        logout(request)
        return Response({"ok": True}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name="dispatch")
class StaffMeView(APIView):
    """GET /api/staff/me/

    The frontend's entire auth gate. Returns the user payload if the
    request carries a valid session cookie AND the user is staff; else
    401. Non-staff authenticated users get 401 too (they're a customer
    who can't see the admin app, full stop) — the gate is "staff
    session" not just "authenticated".
    """

    authentication_classes: list = [_CsrfExemptSessionAuthentication]
    permission_classes: list = []

    def get(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.is_staff:
            return Response(
                {"detail": "Not authenticated."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(_user_payload(user), status=status.HTTP_200_OK)
