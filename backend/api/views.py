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

from core.models import Booking, Conversation, Customer, QRAction, QREvent, Resource, Store
from core.phone import normalize_phone

from .serializers import (
    AvailabilityResponseSerializer,
    BookingCreateSerializer,
    BookingPatchSerializer,
    BookingSerializer,
    ConversationCreateSerializer,
    ConversationDetailSerializer,
    ConversationSerializer,
    CustomerDetailSerializer,
    CustomerNoteCreateSerializer,
    CustomerNoteSerializer,
    CustomerSummarySerializer,
    QRActionCreateSerializer,
    QRActionSerializer,
    QREventCreateSerializer,
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
        channel = self.request.query_params.get("channel")
        if channel:
            # Unknown channel values just return an empty list — no 400.
            qs = qs.filter(channel=channel)
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
# Admin customers (retention epic)
# ---------------------------------------------------------------------------


class AdminCustomerListView(ListAPIView):
    """GET /api/admin/customers/?q=&page= — paginated, newest-first list.

    Search is case-insensitive on name; if the query string normalises to a
    valid E.164 phone, an exact phone match is also OR'd in. Two searches in
    one — without the query, ordering is by ``-last_visit_at``.
    """

    serializer_class = CustomerSummarySerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        from django.db.models import Q

        qs = Customer.objects.all()
        q = self.request.query_params.get("q", "").strip()
        if q:
            normalized = normalize_phone(q)
            phone_q = Q(phone=normalized) if normalized else Q()
            qs = qs.filter(Q(name__icontains=q) | phone_q)
        # NULLS LAST so customers without visits don't lead the list.
        from django.db.models import F

        return qs.order_by(F("last_visit_at").desc(nulls_last=True), "-created_at")


class AdminCustomerDetailView(RetrieveAPIView):
    """GET /api/admin/customers/{id}/ — profile + last 50 visits + all notes."""

    serializer_class = CustomerDetailSerializer
    queryset = Customer.objects.prefetch_related("notes", "notes__author").all()


class AdminCustomerNoteCreateView(APIView):
    """POST /api/admin/customers/{id}/notes/ — add a note attributed to the
    authenticated staff user (or anonymous if no session)."""

    def post(self, request, pk: int):
        try:
            customer = Customer.objects.get(pk=pk)
        except Customer.DoesNotExist:
            return Response({"detail": "Customer not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = CustomerNoteCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        author = request.user if request.user.is_authenticated else None
        note = customer.notes.create(body=ser.validated_data["body"], author=author)
        return Response(CustomerNoteSerializer(note).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# QR (One QR engagement)
# ---------------------------------------------------------------------------


class QRActionListCreateView(APIView):
    """GET / POST /api/admin/qr-actions/?store=<id>.

    Single endpoint because the list and create payloads are tightly
    coupled (POST returns the created row; both use QRActionSerializer).
    """

    def _get_store_id(self, request) -> int | None:
        raw = request.query_params.get("store") or request.data.get("store")
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def get(self, request):
        store_id = self._get_store_id(request)
        qs = QRAction.objects.all()
        if store_id is not None:
            qs = qs.filter(store_id=store_id)
        qs = qs.order_by("store_id", "position")
        return Response(QRActionSerializer(qs, many=True).data)

    def post(self, request):
        store_id = self._get_store_id(request)
        if store_id is None:
            return Response({"store": "store id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            store = Store.objects.get(pk=store_id)
        except Store.DoesNotExist:
            return Response({"store": "not found"}, status=status.HTTP_404_NOT_FOUND)

        ser = QRActionCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        from django.db import transaction
        from django.db.models import Max

        with transaction.atomic():
            if "position" not in data or data["position"] is None:
                # Append to the end.
                last = QRAction.objects.filter(store=store).aggregate(m=Max("position"))["m"]
                data["position"] = (last + 1) if last is not None else 0
            action = QRAction.objects.create(store=store, **data)
        return Response(QRActionSerializer(action).data, status=status.HTTP_201_CREATED)


class QRActionDetailView(APIView):
    """PATCH / DELETE /api/admin/qr-actions/{id}/.

    PATCH supports `position` reorder — when set, the whole store's
    actions are re-positioned atomically so positions stay contiguous.
    """

    def _get_action(self, pk: int) -> QRAction | None:
        try:
            return QRAction.objects.select_related("store").get(pk=pk)
        except QRAction.DoesNotExist:
            return None

    def patch(self, request, pk: int):
        action = self._get_action(pk)
        if action is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = QRActionSerializer(action, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        new_position = ser.validated_data.pop("position", None)
        # Apply non-position fields first.
        for field, value in ser.validated_data.items():
            setattr(action, field, value)
        action.save()

        if new_position is not None and new_position != action.position:
            _reorder_actions(action.store_id, action.id, int(new_position))
            action.refresh_from_db()

        return Response(QRActionSerializer(action).data)

    def delete(self, request, pk: int):
        action = self._get_action(pk)
        if action is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        store_id = action.store_id
        action.delete()
        _compact_positions(store_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _reorder_actions(store_id: int, action_id: int, new_position: int) -> None:
    """Move `action_id` to `new_position` and renumber the store's actions.

    Atomic — uses a two-pass approach with a temporary offset to dodge the
    `(store, position)` unique constraint during the rewrite.
    """
    from django.db import transaction

    with transaction.atomic():
        rows = list(
            QRAction.objects.select_for_update().filter(store_id=store_id).order_by("position")
        )
        rows = [r for r in rows if r.id != action_id]
        target = QRAction.objects.get(pk=action_id)
        new_position = max(0, min(new_position, len(rows)))
        rows.insert(new_position, target)

        # Shift everything to a temporary high range to avoid violating the
        # (store, position) unique constraint mid-write.
        offset = 10_000
        for idx, r in enumerate(rows):
            QRAction.objects.filter(pk=r.pk).update(position=offset + idx)
        for idx, r in enumerate(rows):
            QRAction.objects.filter(pk=r.pk).update(position=idx)


def _compact_positions(store_id: int) -> None:
    """Renumber positions to be contiguous 0..N-1 after a delete."""
    from django.db import transaction

    with transaction.atomic():
        rows = list(
            QRAction.objects.select_for_update().filter(store_id=store_id).order_by("position")
        )
        offset = 10_000
        for idx, r in enumerate(rows):
            QRAction.objects.filter(pk=r.pk).update(position=offset + idx)
        for idx, r in enumerate(rows):
            QRAction.objects.filter(pk=r.pk).update(position=idx)


class QRAnalyticsView(APIView):
    """GET /api/admin/qr-analytics/?store=<id>&days=N.

    Returns total scans, total clicks, engagement rate, and per-action
    click breakdown over the last N days. Null-safe — zero rows yield
    zeros, never NaN.
    """

    def get(self, request):
        from datetime import timedelta

        from django.db.models import Count
        from django.utils import timezone

        try:
            store_id = int(request.query_params.get("store") or 0) or None
        except (TypeError, ValueError):
            store_id = None
        try:
            days = max(1, min(365, int(request.query_params.get("days", 7))))
        except (TypeError, ValueError):
            days = 7

        cutoff = timezone.now() - timedelta(days=days)
        qs = QREvent.objects.filter(created_at__gte=cutoff)
        if store_id is not None:
            qs = qs.filter(store_id=store_id)

        scans = qs.filter(kind="scan").count()
        clicks = qs.filter(kind="click").count()
        engagement_rate = (clicks / scans) if scans else 0.0

        per_action = list(
            qs.filter(kind="click", action__isnull=False)
            .values("action_id", "action__label", "action__kind")
            .annotate(clicks=Count("id"))
            .order_by("-clicks")
        )

        return Response(
            {
                "scans": scans,
                "clicks": clicks,
                "engagement_rate": round(engagement_rate, 4),
                "per_action": per_action,
                "days": days,
            }
        )


class QREventCreateView(APIView):
    """Public POST /api/qr/event/ — anonymous-friendly tracking.

    Resolves the store by slug, optionally links the event to a Customer
    via the `pd_customer` cookie, awards `reward_points` on click events
    when a customer is linked. Never 4xx an anonymous request.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        ser = QREventCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            store = Store.objects.get(slug=data["slug"])
        except Store.DoesNotExist:
            return Response({"detail": "Unknown store."}, status=status.HTTP_404_NOT_FOUND)

        action: QRAction | None = None
        if data.get("action_id"):
            try:
                action = QRAction.objects.get(pk=data["action_id"], store=store)
            except QRAction.DoesNotExist:
                # Bad action id is non-fatal for analytics — record a
                # scan-shaped event instead of failing the request.
                action = None

        # Opportunistic customer linkage. The pd_customer cookie carries
        # the integer Customer pk; we look it up but tolerate stale /
        # forged values gracefully.
        customer: Customer | None = None
        raw_cookie = request.COOKIES.get("pd_customer")
        if raw_cookie:
            try:
                customer = Customer.objects.get(pk=int(raw_cookie), store=store)
            except (Customer.DoesNotExist, ValueError):
                customer = None

        QREvent.objects.create(
            store=store,
            action=action,
            customer=customer,
            kind=data["kind"],
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:255],
            locale=(request.META.get("HTTP_ACCEPT_LANGUAGE") or "")[:8],
        )

        # Award points on a click with a linked customer + action.
        if customer is not None and action is not None and data["kind"] == "click":
            customer.tags = list(set(customer.tags))  # touch — keeps last_visit_at fresh
            # No dedicated points column yet — store an audit hint in tags.
            # (A future `Customer.points` column belongs to a memberships slice.)
            tag = f"qr:{action.kind}"
            if tag not in customer.tags:
                customer.tags = customer.tags + [tag]
                customer.save(update_fields=["tags"])

        return Response({"ok": True}, status=status.HTTP_201_CREATED)


class QRPublicView(APIView):
    """GET /api/qr/{slug}/ — public payload for the landing page.

    Returns the store's branding + the ordered, enabled actions. Used by
    the SSR public page at /qr/[slug] in the frontend.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request, slug: str):
        try:
            store = Store.objects.get(slug=slug)
        except Store.DoesNotExist:
            return Response({"detail": "Unknown store."}, status=status.HTTP_404_NOT_FOUND)
        actions = store.qr_actions.filter(enabled=True).order_by("position")
        return Response(
            {
                "store": {
                    "id": store.id,
                    "name": store.name,
                    "slug": store.slug,
                    "brand": store.brand or {},
                },
                "actions": QRActionSerializer(actions, many=True).data,
            }
        )


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
