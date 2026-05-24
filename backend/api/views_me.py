"""Customer-scoped /api/me/* endpoints (task #167).

Every view returns 401 if ``request.customer is None`` (set by
``CustomerSessionMiddleware``). Booking ownership is enforced by
filtering on ``customer_id == request.customer.id`` so a customer can
never see / mutate another customer's row.

Endpoints:
  - GET    /api/me/                  — profile
  - PATCH  /api/me/                  — update name (phone is read-only)
  - GET    /api/me/bookings/         — upcoming|past, paginated
  - POST   /api/me/bookings/{id}/reschedule/
  - POST   /api/me/bookings/{id}/cancel/

Notification SMS for reschedule / cancel routes through the existing
v4 ``enqueue_message`` adapter (templates ``booking_rescheduled`` and
``booking_cancelled`` added in task #166's templates module).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.memberships import award_points, current_balance
from core.models import Booking, BookingStatus, Customer, Redemption, Reward


def _unauthorized() -> Response:
    return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class MeProfileSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=200, allow_blank=True)
    phone = serializers.CharField(read_only=True)
    store_slug = serializers.CharField(read_only=True)


class MyBookingSerializer(serializers.Serializer):
    """Shape of one booking in the portal's list/detail responses.

    Mirrors what the customer's UI actually needs: ids, the resource
    summary, the timing, and the current status. Deliberately omits
    ``customer_phone`` / ``customer_name`` (the customer already knows).
    """

    id = serializers.IntegerField()
    start_at = serializers.DateTimeField(source="start_time")
    end_at = serializers.DateTimeField(source="end_time")
    status = serializers.CharField()
    resource = serializers.SerializerMethodField()

    def get_resource(self, obj):
        r = obj.resource
        return {"id": r.id, "name": r.name, "type": r.type}


class RescheduleSerializer(serializers.Serializer):
    start_at = serializers.DateTimeField()
    end_at = serializers.DateTimeField()


# ---------------------------------------------------------------------------
# /api/me/  — profile
# ---------------------------------------------------------------------------


class MeView(APIView):
    """GET PATCH /api/me/ — the logged-in customer's profile."""

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        if getattr(request, "customer", None) is None:
            return _unauthorized()
        c = request.customer
        return Response(
            {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "store_slug": c.store.slug,
            }
        )

    def patch(self, request):
        if getattr(request, "customer", None) is None:
            return _unauthorized()
        # Only `name` is editable — phone changes need staff (anti-takeover).
        name = request.data.get("name")
        if name is None:
            return Response({"name": "This field is required."}, status=400)
        request.customer.name = str(name)[:200]
        request.customer.save(update_fields=["name"])
        c = request.customer
        return Response(
            {
                "id": c.id,
                "name": c.name,
                "phone": c.phone,
                "store_slug": c.store.slug,
            }
        )


# ---------------------------------------------------------------------------
# /api/me/bookings/ — list, paginated
# ---------------------------------------------------------------------------


class MyBookingsView(APIView):
    """GET /api/me/bookings/?status=upcoming|past&limit=&offset="""

    authentication_classes: list = []
    permission_classes: list = []

    DEFAULT_LIMIT = 20
    MAX_LIMIT = 50

    def get(self, request):
        if getattr(request, "customer", None) is None:
            return _unauthorized()

        try:
            limit = int(request.query_params.get("limit", self.DEFAULT_LIMIT))
        except (TypeError, ValueError):
            limit = self.DEFAULT_LIMIT
        limit = max(1, min(self.MAX_LIMIT, limit))

        try:
            offset = max(0, int(request.query_params.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0

        status_filter = (request.query_params.get("status") or "upcoming").lower()
        now = timezone.now()
        qs = Booking.objects.select_related("resource").filter(customer=request.customer)
        if status_filter == "upcoming":
            qs = qs.filter(start_time__gte=now).exclude(
                status__in=[BookingStatus.CANCELLED, BookingStatus.COMPLETED]
            )
            qs = qs.order_by("start_time")
        else:
            # `past`: everything else — past or cancelled / completed.
            from django.db.models import Q

            qs = qs.filter(
                Q(start_time__lt=now)
                | Q(status__in=[BookingStatus.CANCELLED, BookingStatus.COMPLETED])
            )
            qs = qs.order_by("-start_time")

        total = qs.count()
        rows = list(qs[offset : offset + limit])
        return Response(
            {
                "results": MyBookingSerializer(rows, many=True).data,
                "total": total,
                "has_more": offset + len(rows) < total,
            }
        )


# ---------------------------------------------------------------------------
# /api/me/bookings/{id}/reschedule/
# ---------------------------------------------------------------------------


class MyBookingRescheduleView(APIView):
    """POST /api/me/bookings/{id}/reschedule/

    Validates ownership + new-time sanity + 50%-duration anti-abuse cap,
    then UPDATEs the booking. Overlap check is the DB's `EXCLUDE USING
    gist` constraint — IntegrityError → 409.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request, pk: int):
        if getattr(request, "customer", None) is None:
            return _unauthorized()

        booking = Booking.objects.filter(pk=pk, customer=request.customer).first()
        if booking is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = RescheduleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        start_at = ser.validated_data["start_at"]
        end_at = ser.validated_data["end_at"]

        now = timezone.now()
        if start_at < now:
            return Response(
                {"detail": "start_at must be in the future."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if end_at <= start_at:
            return Response(
                {"detail": "end_at must be after start_at."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 50%-duration anti-abuse: don't let a 1h booking grow to a 6h one.
        original = (booking.end_time - booking.start_time).total_seconds()
        new = (end_at - start_at).total_seconds()
        if new > original * 1.5:
            return Response(
                {"detail": "Reschedule cannot exceed 150% of original duration."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        date_old = booking.start_time.strftime("%Y-%m-%d %H:%M")
        booking.start_time = start_at
        booking.end_time = end_at
        try:
            booking.save(update_fields=["start_time", "end_time"])
        except IntegrityError:
            return Response(
                {
                    "detail": "The requested time slot is already booked.",
                    "conflicting_booking_id": None,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Notify the customer — fire-and-forget enqueue.
        try:
            from outbound.api import enqueue_message

            enqueue_message(
                request.customer,
                "booking_rescheduled",
                {
                    "date_old": date_old,
                    "date_new": booking.start_time.strftime("%Y-%m-%d %H:%M"),
                },
                channel="sms",
                reference=f"booking:{booking.id}:rescheduled:{int(booking.start_time.timestamp())}",
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "reschedule SMS enqueue failed booking=%s", booking.id
            )

        return Response(MyBookingSerializer(booking).data)


# ---------------------------------------------------------------------------
# /api/me/bookings/{id}/cancel/
# ---------------------------------------------------------------------------


class MyBookingCancelView(APIView):
    """POST /api/me/bookings/{id}/cancel/

    Enforces the store's `cancellation_lead_hours` policy: inside the
    window returns 409 and tells the customer to contact staff.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request, pk: int):
        if getattr(request, "customer", None) is None:
            return _unauthorized()

        booking = (
            Booking.objects.select_related("resource__store")
            .filter(pk=pk, customer=request.customer)
            .first()
        )
        if booking is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        store = booking.resource.store
        lead_hours = int(getattr(store, "cancellation_lead_hours", 24))
        lead_window = timedelta(hours=lead_hours)
        if booking.start_time - timezone.now() < lead_window:
            return Response(
                {
                    "error": "lead_time_violation",
                    "lead_hours": lead_hours,
                    "contact": "Please contact staff",
                },
                status=status.HTTP_409_CONFLICT,
            )

        date_str = booking.start_time.strftime("%Y-%m-%d %H:%M")
        booking.status = BookingStatus.CANCELLED
        booking.save(update_fields=["status"])

        try:
            from outbound.api import enqueue_message

            enqueue_message(
                request.customer,
                "booking_cancelled",
                {"date": date_str},
                channel="sms",
                reference=f"booking:{booking.id}:cancelled",
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "cancel SMS enqueue failed booking=%s", booking.id
            )

        return Response({"status": "cancelled"})


# ---------------------------------------------------------------------------
# /api/me/membership/  +  /api/me/redeem/  (task #168)
# ---------------------------------------------------------------------------


class RedeemSerializer(serializers.Serializer):
    reward_id = serializers.IntegerField()


class MyMembershipView(APIView):
    """GET /api/me/membership/ — same payload shape as v4's admin MembershipView.

    Delegates to the existing ``MembershipView.get`` so the customer
    surface and the admin surface stay byte-for-byte identical and any
    future tweak (e.g. a new tier badge field) lands in both at once.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        if getattr(request, "customer", None) is None:
            return _unauthorized()

        # Reuse v4's logic — passing request + the customer's own pk
        # keeps the response shape identical.
        from .views_memberships import MembershipView

        return MembershipView().get(request, request.customer.pk)


class MyRedeemView(APIView):
    """POST /api/me/redeem/ body `{reward_id}`.

    Customer-initiated redeem. Same atomic flow as v4's admin
    `RedeemView`: balance check + `award_points(-cost)` + Redemption row,
    under `select_for_update` on the customer row so a concurrent redeem
    can't double-spend. Cross-store rewards return 400.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request):
        if getattr(request, "customer", None) is None:
            return _unauthorized()

        ser = RedeemSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        customer = request.customer

        try:
            reward = Reward.objects.get(
                pk=ser.validated_data["reward_id"],
                store_id=customer.store_id,
                enabled=True,
            )
        except Reward.DoesNotExist:
            raise ValidationError({"reward_id": "Reward not found or not available."})

        with transaction.atomic():
            Customer.objects.select_for_update().filter(pk=customer.pk).first()
            balance = current_balance(customer)
            if balance < reward.cost_points:
                return Response(
                    {
                        "error": "insufficient_points",
                        "balance": balance,
                        "cost": reward.cost_points,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            # Customer-initiated redeem — no staff author.
            pt = award_points(
                customer,
                -reward.cost_points,
                "redemption",
                reference=str(reward.id),
                author=None,
            )
            redemption = Redemption.objects.create(
                customer=customer, reward=reward, transaction=pt, staff=None
            )

        return Response(
            {
                "redemption_id": redemption.id,
                "transaction_id": pt.id,
                "balance": pt.balance_after,
            },
            status=status.HTTP_201_CREATED,
        )
