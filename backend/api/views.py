"""
DRF views for the PlayDesk REST API.

Endpoints covered:
  GET  /api/resources/
  GET  /api/resources/{id}/
  GET  /api/resources/{id}/availability/?date=YYYY-MM-DD
  GET  POST /api/bookings/
  GET  PATCH DELETE /api/bookings/{id}/
  POST /api/conversations/
  GET  /api/conversations/{id}/
  GET  /api/admin/conversations/
  GET  /api/admin/bookings/

The booking overlap 409 is raised by the DB exclusion constraint.
We catch IntegrityError and return HTTP 409 — no Python-level pre-check.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Booking, Conversation, Resource

from .serializers import (
    AvailabilityResponseSerializer,
    BookingCreateSerializer,
    BookingPatchSerializer,
    BookingSerializer,
    ConversationCreateSerializer,
    ConversationDetailSerializer,
    ConversationSerializer,
    ResourceSerializer,
)

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class ResourceListView(ListAPIView):
    """GET /api/resources/ — list resources, optionally filtered by type."""

    serializer_class = ResourceSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Resource.objects.select_related("store").all()
        resource_type = self.request.query_params.get("type")
        if resource_type:
            valid_types = {"console", "room", "table"}
            if resource_type not in valid_types:
                raise ValidationError(
                    {"type": f"Invalid type. Must be one of: {sorted(valid_types)}."}
                )
            qs = qs.filter(type=resource_type)
        store_id = self.request.query_params.get("store_id")
        if store_id:
            qs = qs.filter(store_id=store_id)
        return qs


class ResourceDetailView(RetrieveAPIView):
    """GET /api/resources/{id}/"""

    serializer_class = ResourceSerializer
    queryset = Resource.objects.select_related("store").all()


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def _compute_availability(resource: Resource, query_date: date) -> dict:
    """
    Return open time slots for *resource* on *query_date*.

    Algorithm:
      1. Parse the store's business_hours for the weekday.
      2. Fetch all non-cancelled bookings for that date.
      3. Subtract booked intervals from the business window.
      4. Return the remaining free slots.

    business_hours format expected:
      {"mon": {"open": "10:00", "close": "22:00"}, ...}
    or keyed by weekday index ("0"–"6", 0=Monday).
    """
    store = resource.store
    bh = store.business_hours or {}

    # Map weekday to day key
    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    weekday = query_date.weekday()  # 0=Monday
    day_key_name = day_names[weekday]
    day_key_int = str(weekday)

    hours = bh.get(day_key_name) or bh.get(day_key_int)

    tz_str = store.timezone or "UTC"
    try:
        import zoneinfo

        store_tz = zoneinfo.ZoneInfo(tz_str)
    except Exception:
        store_tz = UTC

    if not hours or not hours.get("open") or not hours.get("close"):
        # Closed on this day — no available slots
        return {"available": [], "suggestions": []}

    def _parse_time(t: str, d: date, tz) -> datetime:
        h, m = map(int, t.split(":"))
        naive = datetime(d.year, d.month, d.day, h, m)
        return naive.replace(tzinfo=tz)

    biz_start = _parse_time(hours["open"], query_date, store_tz)
    biz_end = _parse_time(hours["close"], query_date, store_tz)

    # Fetch active bookings for this resource on this date (UTC-based comparison)
    day_start_utc = datetime(query_date.year, query_date.month, query_date.day, 0, 0, tzinfo=UTC)
    day_end_utc = day_start_utc + timedelta(days=1)

    bookings = (
        Booking.objects.filter(
            resource=resource,
            start_time__lt=day_end_utc,
            end_time__gt=day_start_utc,
        )
        .exclude(status="cancelled")
        .order_by("start_time")
        .values("start_time", "end_time")
    )

    # Subtract booked intervals
    free_slots = []
    cursor = biz_start

    for bk in bookings:
        bk_start = bk["start_time"]
        bk_end = bk["end_time"]

        # Clamp to business window
        bk_start = max(bk_start, biz_start)
        bk_end = min(bk_end, biz_end)

        if bk_start > cursor:
            free_slots.append({"start": cursor, "end": bk_start})
        cursor = max(cursor, bk_end)

    if cursor < biz_end:
        free_slots.append({"start": cursor, "end": biz_end})

    return {"available": free_slots, "suggestions": []}


class ResourceAvailabilityView(APIView):
    """GET /api/resources/{id}/availability/?date=YYYY-MM-DD"""

    def get(self, request, pk):
        try:
            resource = Resource.objects.select_related("store").get(pk=pk)
        except Resource.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        date_str = request.query_params.get("date")
        if not date_str:
            raise ValidationError({"date": "This field is required."})

        try:
            query_date = date.fromisoformat(date_str)
        except ValueError:
            raise ValidationError({"date": "Date must be in YYYY-MM-DD format."})

        slots = _compute_availability(resource, query_date)

        payload = {
            "resource_id": resource.pk,
            "date": query_date.isoformat(),
            "available": slots["available"],
            "suggestions": slots["suggestions"],
        }
        serializer = AvailabilityResponseSerializer(payload)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------


class BookingListCreateView(ListCreateAPIView):
    """GET POST /api/bookings/"""

    pagination_class = StandardPagination

    def get_serializer_class(self):
        if self.request.method == "POST":
            return BookingCreateSerializer
        return BookingSerializer

    def get_queryset(self):
        qs = Booking.objects.select_related("resource", "conversation").all()
        params = self.request.query_params

        resource_id = params.get("resource_id")
        if resource_id:
            qs = qs.filter(resource_id=resource_id)

        booking_status = params.get("status")
        if booking_status:
            qs = qs.filter(status=booking_status)

        date_str = params.get("date")
        if date_str:
            try:
                d = date.fromisoformat(date_str)
            except ValueError:
                raise ValidationError({"date": "Date must be in YYYY-MM-DD format."})
            day_start = datetime(d.year, d.month, d.day, tzinfo=UTC)
            day_end = day_start + timedelta(days=1)
            qs = qs.filter(start_time__gte=day_start, start_time__lt=day_end)

        source = params.get("source")
        if source:
            qs = qs.filter(source=source)

        return qs

    def create(self, request, *args, **kwargs):
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            booking = serializer.save()
        except IntegrityError:
            return Response(
                {
                    "detail": "The requested time slot is already booked.",
                    "conflicting_booking_id": None,
                    "suggestions": [],
                },
                status=status.HTTP_409_CONFLICT,
            )
        out = BookingSerializer(booking)
        return Response(out.data, status=status.HTTP_201_CREATED)


class BookingDetailView(APIView):
    """GET PATCH DELETE /api/bookings/{id}/"""

    def _get_booking(self, pk):
        try:
            return Booking.objects.select_related("resource", "conversation").get(pk=pk)
        except Booking.DoesNotExist:
            return None

    def get(self, request, pk):
        booking = self._get_booking(pk)
        if not booking:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(BookingSerializer(booking).data)

    def patch(self, request, pk):
        booking = self._get_booking(pk)
        if not booking:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = BookingPatchSerializer(booking, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            booking = serializer.save()
        except IntegrityError:
            return Response(
                {
                    "detail": "The requested time slot is already booked.",
                    "conflicting_booking_id": None,
                    "suggestions": [],
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(BookingSerializer(booking).data)

    def delete(self, request, pk):
        booking = self._get_booking(pk)
        if not booking:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        booking.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


class ConversationCreateView(APIView):
    """POST /api/conversations/"""

    def post(self, request):
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer_identifier = serializer.validated_data.get("customer_identifier") or str(
            uuid.uuid4()
        )
        conversation = Conversation.objects.create(customer_identifier=customer_identifier)
        return Response(ConversationSerializer(conversation).data, status=status.HTTP_201_CREATED)


class ConversationDetailView(RetrieveAPIView):
    """GET /api/conversations/{id}/"""

    serializer_class = ConversationDetailSerializer
    queryset = Conversation.objects.prefetch_related("messages").all()


# ---------------------------------------------------------------------------
# Admin views
# ---------------------------------------------------------------------------


class AdminConversationListView(ListAPIView):
    """GET /api/admin/conversations/ — staff visibility, newest first."""

    serializer_class = ConversationSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Conversation.objects.all().order_by("-started_at")
        conv_status = self.request.query_params.get("status")
        if conv_status:
            qs = qs.filter(status=conv_status)
        ordering = self.request.query_params.get("ordering")
        if ordering:
            qs = qs.order_by(ordering)
        return qs


class AdminBookingListView(ListAPIView):
    """GET /api/admin/bookings/ — staff visibility, newest first."""

    serializer_class = BookingSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Booking.objects.select_related("resource", "conversation").order_by("-created_at")
        params = self.request.query_params

        booking_status = params.get("status")
        if booking_status:
            qs = qs.filter(status=booking_status)

        resource_id = params.get("resource_id")
        if resource_id:
            qs = qs.filter(resource_id=resource_id)

        date_str = params.get("date")
        if date_str:
            try:
                d = date.fromisoformat(date_str)
            except ValueError:
                raise ValidationError({"date": "Date must be in YYYY-MM-DD format."})
            day_start = datetime(d.year, d.month, d.day, tzinfo=UTC)
            day_end = day_start + timedelta(days=1)
            qs = qs.filter(start_time__gte=day_start, start_time__lt=day_end)

        return qs


# ---------------------------------------------------------------------------
# Stripe webhook (enhancements epic)
# ---------------------------------------------------------------------------


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request):
    """
    POST /api/webhooks/stripe/

    Confirms a booking when its Stripe deposit is paid. On a verified
    `checkout.session.completed` event, the booking carried in the session
    metadata is flipped pending_payment → confirmed. Idempotent: a repeat
    delivery — or a booking no longer pending — simply matches no rows.
    """
    from core.models import BookingStatus
    from core.payments import verify_webhook_event

    try:
        event = verify_webhook_event(request.body, request.META.get("HTTP_STRIPE_SIGNATURE", ""))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    if event.get("type") == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        booking_id = (session.get("metadata") or {}).get("booking_id")
        if booking_id:
            Booking.objects.filter(pk=booking_id, status=BookingStatus.PENDING_PAYMENT).update(
                status=BookingStatus.CONFIRMED
            )

    return JsonResponse({"received": True})
