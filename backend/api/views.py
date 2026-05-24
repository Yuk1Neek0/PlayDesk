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
    """GET /api/resources/ — list resources, optionally filtered by type.

    Scoped to ``request.store`` by default; an explicit ``?store_id=`` query
    string still wins so legacy callers (the agent tool dispatch path, the
    booking page that knows its own store) keep working.
    """

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
        elif self.request.store is not None:
            qs = qs.filter(store=self.request.store)
        return qs


class ResourceDetailView(RetrieveAPIView):
    """GET /api/resources/{id}/ — 404 when the resource belongs to another store."""

    serializer_class = ResourceSerializer

    def get_queryset(self):
        qs = Resource.objects.select_related("store").all()
        if self.request.store is not None:
            qs = qs.filter(store=self.request.store)
        return qs


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
        if self.request.store is not None:
            qs = qs.filter(resource__store=self.request.store)
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

        # v8 pricing-rules: optimistic-concurrency check. The frontend
        # passes ``expected_total_amount`` (the price the customer saw on
        # the booking page). If a rule changed between quote and submit
        # and the recomputed total now differs by > $0.01, return 409 with
        # the new quote so the UI can re-prompt for confirmation. Old
        # clients that omit the field just accept whatever the server
        # computes.
        expected_raw = request.data.get("expected_total_amount")
        if expected_raw is not None:
            from decimal import Decimal, InvalidOperation

            from pricing.engine import compute_quote

            try:
                expected_total = Decimal(str(expected_raw))
            except (InvalidOperation, ValueError, TypeError):
                return Response(
                    {"expected_total_amount": "must be a number"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            validated = serializer.validated_data
            resource = validated["resource"]
            try:
                customer = resource.store.customers.filter(
                    phone=validated["customer_phone"]
                ).first()
            except Exception:  # noqa: BLE001 — defensive; new customer is fine
                customer = None
            quote = compute_quote(
                resource,
                validated["start_time"],
                validated["end_time"],
                customer=customer,
            )
            if abs(quote.total_amount - expected_total) > Decimal("0.01"):
                return Response(
                    {"error": "quote_changed", "new_quote": quote.to_dict()},
                    status=status.HTTP_409_CONFLICT,
                )

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

        # v9 billing-payments: wire optional PaymentIntent if the store
        # demands a deposit. Computed AFTER the booking row exists — this
        # is the deliberate ordering for the merge with v8 pricing-rules
        # (which will compute `total_amount` BEFORE the booking is saved).
        payment_payload = _maybe_open_deposit(booking)
        out = BookingSerializer(booking)
        body = dict(out.data)
        if payment_payload:
            body.update(payment_payload)
        return Response(body, status=status.HTTP_201_CREATED)


class BookingDetailView(APIView):
    """GET PATCH DELETE /api/bookings/{id}/ — scoped to ``request.store``.

    Cross-store ids return 404 so the response can't be used to enumerate
    bookings in other locations.
    """

    def _get_booking(self, pk):
        qs = Booking.objects.select_related("resource", "conversation")
        if self.request.store is not None:
            qs = qs.filter(resource__store=self.request.store)
        try:
            return qs.get(pk=pk)
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
        conversation = Conversation.objects.create(
            customer_identifier=customer_identifier,
            store=request.store,
        )
        return Response(ConversationSerializer(conversation).data, status=status.HTTP_201_CREATED)


class ConversationDetailView(RetrieveAPIView):
    """GET /api/conversations/{id}/"""

    serializer_class = ConversationDetailSerializer
    queryset = Conversation.objects.prefetch_related("messages").all()


# ---------------------------------------------------------------------------
# Admin views
# ---------------------------------------------------------------------------


class AdminConversationListView(ListAPIView):
    """GET /api/admin/conversations/ — staff visibility, newest first.

    Scoped to ``request.store`` so each location sees only its own
    conversations. Backed by ``Conversation.store`` (task #159).
    """

    serializer_class = ConversationSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Conversation.objects.all().order_by("-started_at")
        if self.request.store is not None:
            qs = qs.filter(store=self.request.store)
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
    """GET /api/admin/bookings/ — staff visibility, newest first.

    Scoped to ``request.store`` via the ``resource__store`` chain.
    """

    serializer_class = BookingSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Booking.objects.select_related("resource", "conversation").order_by("-created_at")
        if self.request.store is not None:
            qs = qs.filter(resource__store=self.request.store)
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

        # v10b checkin: optional filter on the check-in dimension. `yes` =
        # only checked-in bookings, `no` = only confirmed-but-not-yet
        # bookings. Anything else is silently ignored to keep the
        # default-list behaviour unchanged for legacy callers.
        checked_in = params.get("checked_in")
        if checked_in == "yes":
            qs = qs.filter(status="checked_in")
        elif checked_in == "no":
            qs = qs.filter(status="confirmed", checked_in_at__isnull=True)

        return qs


# ---------------------------------------------------------------------------
# Admin customers (retention epic)
# ---------------------------------------------------------------------------


class AdminCustomerListView(ListAPIView):
    """GET /api/admin/customers/?q=&page=&cohort= — paginated, newest-first list.

    Search is case-insensitive on name; if the query string normalises to a
    valid E.164 phone, an exact phone match is also OR'd in. Two searches in
    one — without the query, ordering is by ``-last_visit_at``.

    v11c retention: accepts ``?cohort=new|active|at_risk|dormant|lost`` and
    returns store-scoped per-cohort counts in the response body so the
    admin chip toolbar can render counts without a separate query.
    """

    serializer_class = CustomerSummarySerializer
    pagination_class = StandardPagination

    # Allowlist for the ?cohort= filter — anything else is silently ignored
    # (matches the existing channel / status filter behaviour).
    _COHORT_VALUES = frozenset({"new", "active", "at_risk", "dormant", "lost"})

    def _store_scoped_qs(self):
        qs = Customer.objects.all()
        if self.request.store is not None:
            qs = qs.filter(store=self.request.store)
        return qs

    def get_queryset(self):
        from django.db.models import F, Q

        qs = self._store_scoped_qs()
        q = self.request.query_params.get("q", "").strip()
        if q:
            normalized = normalize_phone(q)
            phone_q = Q(phone=normalized) if normalized else Q()
            qs = qs.filter(Q(name__icontains=q) | phone_q)
        cohort = self.request.query_params.get("cohort", "").strip()
        if cohort in self._COHORT_VALUES:
            qs = qs.filter(cohort=cohort)
        # NULLS LAST so customers without visits don't lead the list.
        return qs.order_by(F("last_visit_at").desc(nulls_last=True), "-created_at")

    def list(self, request, *args, **kwargs):
        from django.db.models import Count

        response = super().list(request, *args, **kwargs)
        # Store-scoped per-cohort counts — independent of the active filter
        # so the chip labels stay stable as staff toggle between cohorts.
        # Single GROUP BY on an indexed column — cheap.
        counts_qs = self._store_scoped_qs().values("cohort").annotate(count=Count("id"))
        counts = {row["cohort"]: row["count"] for row in counts_qs}
        # Always include every label, even empty, so the UI doesn't have
        # to defensively check for missing keys.
        response.data["cohort_counts"] = {
            label: counts.get(label, 0) for label in self._COHORT_VALUES
        }
        return response


class AdminCustomerDetailView(RetrieveAPIView):
    """GET /api/admin/customers/{id}/ — profile + last 50 visits + all notes.

    Cross-store ids return 404 — a customer that belongs to another store
    is indistinguishable from a missing one so the response can't leak
    other stores' customer ids.
    """

    serializer_class = CustomerDetailSerializer

    def get_queryset(self):
        qs = Customer.objects.prefetch_related("notes", "notes__author").all()
        if self.request.store is not None:
            qs = qs.filter(store=self.request.store)
        return qs


class AdminCustomerNoteCreateView(APIView):
    """POST /api/admin/customers/{id}/notes/ — add a note attributed to the
    authenticated staff user (or anonymous if no session).

    Cross-store customer ids return 404.
    """

    def post(self, request, pk: int):
        qs = Customer.objects.all()
        if request.store is not None:
            qs = qs.filter(store=request.store)
        try:
            customer = qs.get(pk=pk)
        except Customer.DoesNotExist:
            return Response({"detail": "Customer not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = CustomerNoteCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        author = request.user if request.user.is_authenticated else None
        note = customer.notes.create(body=ser.validated_data["body"], author=author)
        return Response(CustomerNoteSerializer(note).data, status=status.HTTP_201_CREATED)


# Allowlist of templates the bulk-send endpoint is willing to blast. We
# don't want a staff click to fire arbitrary booking_confirmation /
# payment_receipt copy at the wrong audience — only deliberate
# re-engagement messages are safe to bulk-send.
BULK_SEND_TEMPLATE_ALLOWLIST = frozenset({"re_engagement_60d"})


class AdminCustomerBulkSendView(APIView):
    """POST /api/admin/customers/bulk-send/ — fire one template at a cohort.

    Body: ``{"cohort": "<label>", "template_key": "re_engagement_60d"}``.
    Iterates store-scoped customers in the cohort, skips ``sms_opt_out``,
    enqueues via the v4 outbound layer (which already honours quiet
    hours), writes one ``CustomerNote`` per send for audit.

    Returns ``{sent: N, skipped: M, skip_reasons: {opt_out: K, ...}}``.
    Gated by ``StaffOnlyMiddleware`` (v10a) automatically.
    """

    _COHORT_VALUES = AdminCustomerListView._COHORT_VALUES

    def post(self, request):
        cohort = (request.data.get("cohort") or "").strip()
        template_key = (request.data.get("template_key") or "").strip()

        if cohort not in self._COHORT_VALUES:
            return Response(
                {"detail": f"Unknown cohort {cohort!r}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if template_key not in BULK_SEND_TEMPLATE_ALLOWLIST:
            return Response(
                {"detail": f"Template {template_key!r} is not bulk-sendable."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from outbound.api import enqueue_message

        qs = Customer.objects.filter(cohort=cohort)
        if request.store is not None:
            qs = qs.filter(store=request.store)

        sent = 0
        skip_reasons: dict[str, int] = {}
        author = request.user if request.user.is_authenticated else None

        for customer in qs.iterator(chunk_size=500):
            if "sms_opt_out" in (customer.tags or []):
                skip_reasons["opt_out"] = skip_reasons.get("opt_out", 0) + 1
                continue
            try:
                enqueue_message(
                    customer,
                    template_key,
                    context={
                        "customer_name": customer.name or "there",
                        "store_name": customer.store.name,
                    },
                )
            except Exception as exc:  # noqa: BLE001 — log + count, don't 500.
                reason = f"error:{type(exc).__name__}"
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue
            customer.notes.create(
                body=f"Sent {template_key} via bulk action",
                author=author,
            )
            sent += 1

        return Response(
            {
                "sent": sent,
                "skipped": sum(skip_reasons.values()),
                "skip_reasons": skip_reasons,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# QR (One QR engagement)
# ---------------------------------------------------------------------------


class QRActionListCreateView(APIView):
    """GET / POST /api/admin/qr-actions/?store=<id>.

    Single endpoint because the list and create payloads are tightly
    coupled (POST returns the created row; both use QRActionSerializer).

    Defaults to ``request.store`` when ``?store=`` / ``store`` body field is
    omitted, so admin clients with a current store context don't have to
    repeat it on every call.
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
        elif request.store is not None:
            qs = qs.filter(store=request.store)
        qs = qs.order_by("store_id", "position")
        return Response(QRActionSerializer(qs, many=True).data)

    def post(self, request):
        store_id = self._get_store_id(request)
        if store_id is None and request.store is not None:
            store_id = request.store.pk
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

    Scoped to ``request.store`` — actions belonging to another store
    return 404 to keep ids non-enumerable across locations.
    """

    def _get_action(self, pk: int) -> QRAction | None:
        qs = QRAction.objects.select_related("store")
        if self.request.store is not None:
            qs = qs.filter(store=self.request.store)
        try:
            return qs.get(pk=pk)
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
        if store_id is None and request.store is not None:
            store_id = request.store.pk
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

        event = QREvent.objects.create(
            store=store,
            action=action,
            customer=customer,
            kind=data["kind"],
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:255],
            locale=(request.META.get("HTTP_ACCEPT_LANGUAGE") or "")[:8],
        )

        # Award points on a click with a linked customer + action.
        if customer is not None and action is not None and data["kind"] == "click":
            tag = f"qr:{action.kind}"
            if tag not in customer.tags:
                customer.tags = customer.tags + [tag]
                customer.save(update_fields=["tags"])
            if action.reward_points > 0:
                try:
                    from core.memberships import award_points as _award_points

                    _award_points(customer, action.reward_points, "qr_click", str(event.id))
                except Exception:
                    import logging

                    logging.getLogger(__name__).exception(
                        "award_points failed for QR click event=%s", event.id
                    )

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
# v9 billing-payments — deposit PaymentIntent on booking-create
# ---------------------------------------------------------------------------


def _maybe_open_deposit(booking):
    """If the store demands a deposit, create a Stripe PaymentIntent.

    Returns a dict to merge into the booking-create response when a
    deposit is required (`{requires_payment, client_secret, deposit_amount}`);
    returns None when `deposit_mode='none'` so the response stays
    backwards-compatible.
    """
    import logging
    from decimal import Decimal

    from django.conf import settings

    from billing import stripe_client
    from billing.helpers import calc_deposit
    from billing.models import Payment, PaymentKind, PaymentRowStatus
    from core.models import BookingStatus, PaymentStatus

    log = logging.getLogger(__name__)
    publishable_key = settings.STRIPE_PUBLISHABLE_KEY or ""

    resource = booking.resource
    store = resource.store
    # Pricing source: v8 `total_amount` if landed, else hourly * hours.
    total = getattr(booking, "total_amount", None)
    if total is None:
        hours = Decimal((booking.end_time - booking.start_time).total_seconds() / 3600).quantize(
            Decimal("0.01")
        )
        total = resource.price_per_hour * hours

    deposit = calc_deposit(store, resource, total)
    if deposit <= 0:
        # Either deposit_mode=none or computed to zero. Treat as the
        # legacy "no deposit" path — leave the booking confirmed.
        return None

    booking.payment_status = PaymentStatus.PENDING_PAYMENT
    booking.status = BookingStatus.PENDING
    booking.deposit_amount = deposit
    booking.save(update_fields=["payment_status", "status", "deposit_amount"])

    if not stripe_client.is_configured():
        # Test/dev mode without a real key — create a stub Payment row
        # so the ledger + admin UI render, but skip the Stripe call.
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=deposit,
            currency=store.currency,
            status=PaymentRowStatus.PENDING,
            metadata={"test_mode_stub": True},
        )
        return {
            "requires_payment": True,
            "deposit_amount": str(deposit),
            "client_secret": None,
            "publishable_key": publishable_key,
            "configured": False,
        }

    stripe = stripe_client.get_stripe()
    try:
        intent_kwargs = {
            "amount": int(deposit * 100),
            "currency": store.currency.lower(),
            "metadata": {
                "booking_id": str(booking.id),
                "kind": "deposit",
            },
        }
        if store.stripe_account_id and store.stripe_charges_enabled:
            intent_kwargs["transfer_data"] = {"destination": store.stripe_account_id}
        intent = stripe.PaymentIntent.create(**intent_kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning("PaymentIntent.create failed: %s", exc)
        return {
            "requires_payment": True,
            "deposit_amount": str(deposit),
            "client_secret": None,
            "publishable_key": publishable_key,
            "error": "stripe_unavailable",
        }

    booking.payment_intent_id = intent.id
    booking.save(update_fields=["payment_intent_id"])

    Payment.objects.create(
        store=store,
        booking=booking,
        kind=PaymentKind.DEPOSIT,
        amount=deposit,
        currency=store.currency,
        status=PaymentRowStatus.PENDING,
        stripe_payment_intent_id=intent.id,
    )

    return {
        "requires_payment": True,
        "deposit_amount": str(deposit),
        "client_secret": getattr(intent, "client_secret", None),
        "publishable_key": publishable_key,
    }


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
