"""Public + admin check-in endpoints (v10b checkin).

Public surface — `/api/c/<token>/`:
- GET returns the booking summary + a ``can_check_in`` flag + a
  state-appropriate ``message`` for the customer-facing card.
- POST flips a CONFIRMED booking into CHECKED_IN, stamping
  ``checked_in_at``. Idempotent: a second POST on an already-checked-in
  booking returns 200 with the same payload (not 409).

Both public views have empty ``authentication_classes`` /
``permission_classes`` — the token IS the credential. This is by
design: the customer doesn't sign in, they tap the SMS link.

Admin surface — `/api/admin/bookings/<pk>/check-in/` and
`/.../undo-check-in/`: staff overrides for walk-ins (lost the SMS) or
accidental check-ins. Both write a `CustomerNote` for audit.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Booking, BookingStatus, CustomerNote

from .serializers import BookingSerializer


def _checkin_payload(booking: Booking) -> dict:
    """Build the GET / POST response shape for a check-in lookup.

    Keeps fields tight — the customer page only needs branding, time,
    resource, name. We deliberately don't return phone / total / etc.
    so a leaked token can't be used as a customer-data scrape vector.
    """
    can = booking.status == BookingStatus.CONFIRMED and booking.checked_in_at is None

    if booking.status == BookingStatus.CANCELLED:
        message = "This booking was cancelled"
    elif booking.status == BookingStatus.PENDING_PAYMENT:
        message = "Please complete your deposit first"
    elif booking.status == BookingStatus.CHECKED_IN:
        ts = booking.checked_in_at.strftime("%H:%M") if booking.checked_in_at else "—"
        message = f"Already checked in at {ts}"
    elif booking.status == BookingStatus.COMPLETED:
        message = "This booking is complete"
    elif booking.status == BookingStatus.CONFIRMED:
        message = "Ready to check in"
    else:
        # PENDING / unknown — surface the raw state without a friendly
        # copy. Shouldn't happen for a booking the customer ever saw.
        message = "Booking not ready for check-in"

    return {
        "booking_id": booking.pk,
        "status": booking.status,
        "checked_in_at": (booking.checked_in_at.isoformat() if booking.checked_in_at else None),
        "customer_name": booking.customer_name or "",
        "resource_name": booking.resource.name,
        "start_time": booking.start_time.isoformat(),
        "end_time": booking.end_time.isoformat(),
        "store_slug": booking.resource.store.slug,
        "can_check_in": can,
        "message": message,
    }


def _lookup_by_token(token: str) -> Booking | None:
    """Resolve a check-in token to a Booking, normalising to uppercase.

    Returns ``None`` when no booking matches — the caller should 404.
    """
    if not token:
        return None
    return (
        Booking.objects.select_related("resource", "resource__store", "customer")
        .filter(check_in_token=token.upper())
        .first()
    )


class CheckInInfoView(APIView):
    """GET /api/c/<token>/ — public read of one booking's check-in state."""

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request, token: str):
        booking = _lookup_by_token(token)
        if booking is None:
            return Response(
                {"detail": "Check-in link not found or expired."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_checkin_payload(booking))


class CheckInActionView(APIView):
    """POST /api/c/<token>/check-in/ — public flip to CHECKED_IN."""

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request, token: str):
        booking = _lookup_by_token(token)
        if booking is None:
            return Response(
                {"detail": "Check-in link not found or expired."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Idempotent: a second tap on a checked-in booking returns the
        # same payload. The customer can't tell the difference between
        # "checked in" and "already checked in" beyond the message copy.
        if booking.status == BookingStatus.CHECKED_IN:
            return Response(_checkin_payload(booking))

        if booking.status != BookingStatus.CONFIRMED:
            return Response(_checkin_payload(booking), status=status.HTTP_409_CONFLICT)

        booking.status = BookingStatus.CHECKED_IN
        booking.checked_in_at = timezone.now()
        booking.save(update_fields=["status", "checked_in_at"])
        return Response(_checkin_payload(booking))


# ---------------------------------------------------------------------------
# Admin endpoints — staff manual override
# ---------------------------------------------------------------------------


def _record_note(booking: Booking, author, body: str) -> None:
    """Audit-log the staff action via a CustomerNote.

    Skips silently if the booking has no FK customer — legacy unlinked
    rows shouldn't crash the action, just stay un-audited.
    """
    if booking.customer_id is None:
        return
    real_author = author if (author is not None and author.is_authenticated) else None
    CustomerNote.objects.create(
        customer=booking.customer,
        author=real_author,
        body=body,
    )


def _admin_lookup(request, pk: int) -> Booking | None:
    """Scope an admin lookup to ``request.store`` if the middleware set one."""
    qs = Booking.objects.select_related("resource", "resource__store", "customer")
    store = getattr(request, "store", None)
    if store is not None:
        qs = qs.filter(resource__store=store)
    return qs.filter(pk=pk).first()


class AdminCheckInView(APIView):
    """POST /api/admin/bookings/<pk>/check-in/ — staff manual check-in."""

    def post(self, request, pk: int):
        booking = _admin_lookup(request, pk)
        if booking is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if booking.status != BookingStatus.CONFIRMED:
            return Response(
                {
                    "error": "invalid_state",
                    "detail": f"Cannot manually check in a {booking.status} booking.",
                    "current_status": booking.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        booking.status = BookingStatus.CHECKED_IN
        booking.checked_in_at = now
        booking.save(update_fields=["status", "checked_in_at"])
        _record_note(
            booking,
            request.user,
            f"Manually checked in by staff at {now:%Y-%m-%d %H:%M}.",
        )
        return Response(BookingSerializer(booking).data)


class AdminUndoCheckInView(APIView):
    """POST /api/admin/bookings/<pk>/undo-check-in/ — revert a check-in."""

    def post(self, request, pk: int):
        booking = _admin_lookup(request, pk)
        if booking is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if booking.status != BookingStatus.CHECKED_IN:
            return Response(
                {
                    "error": "invalid_state",
                    "detail": f"Cannot undo check-in for a {booking.status} booking.",
                    "current_status": booking.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking.status = BookingStatus.CONFIRMED
        booking.checked_in_at = None
        booking.save(update_fields=["status", "checked_in_at"])
        _record_note(booking, request.user, "Check-in undone by staff.")
        return Response(BookingSerializer(booking).data)
