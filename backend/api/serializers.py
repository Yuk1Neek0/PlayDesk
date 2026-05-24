"""
DRF serializers for the PlayDesk REST API.

Mirrors the OpenAPI schema definitions in docs/contracts/openapi.yaml.
"""

from rest_framework import serializers

from core.models import (
    Booking,
    Conversation,
    Customer,
    CustomerNote,
    Message,
    QRAction,
    Resource,
)

# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


class ResourceSerializer(serializers.ModelSerializer):
    """Serializes Resource to match the OpenAPI Resource schema."""

    store_id = serializers.IntegerField(source="store.id", read_only=True)
    price_per_hour = serializers.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        model = Resource
        fields = [
            "id",
            "store_id",
            "type",
            "name",
            "capacity",
            "price_per_hour",
            "metadata",
        ]


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


class TimeSlotSerializer(serializers.Serializer):
    """A single open or suggested time slot."""

    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class AvailabilityResponseSerializer(serializers.Serializer):
    """Response shape for GET /api/resources/{id}/availability/."""

    resource_id = serializers.IntegerField()
    date = serializers.DateField()
    available = TimeSlotSerializer(many=True)
    suggestions = TimeSlotSerializer(many=True)


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------


class BookingSerializer(serializers.ModelSerializer):
    """Full Booking read representation."""

    resource_id = serializers.IntegerField(source="resource.id", read_only=True)
    conversation_id = serializers.IntegerField(
        source="conversation.id", read_only=True, allow_null=True
    )

    class Meta:
        model = Booking
        fields = [
            "id",
            "resource_id",
            "conversation_id",
            "customer_name",
            "customer_phone",
            "start_time",
            "end_time",
            "status",
            "source",
            "total_amount",
            "rule_snapshot",
            "refund_amount",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "total_amount",
            "rule_snapshot",
            "refund_amount",
        ]


class BookingCreateSerializer(serializers.ModelSerializer):
    """Deserializes POST /api/bookings/ request body."""

    resource_id = serializers.PrimaryKeyRelatedField(
        queryset=Resource.objects.all(), source="resource"
    )
    conversation_id = serializers.PrimaryKeyRelatedField(
        queryset=Conversation.objects.all(),
        source="conversation",
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Booking
        fields = [
            "resource_id",
            "conversation_id",
            "customer_name",
            "customer_phone",
            "start_time",
            "end_time",
            "source",
        ]

    def validate(self, attrs):
        start = attrs.get("start_time")
        end = attrs.get("end_time")
        if start and end and end <= start:
            raise serializers.ValidationError({"end_time": "end_time must be after start_time."})
        return attrs

    def create(self, validated_data):
        """Resolve a Customer for this booking before saving.

        Phone is normalised to E.164; bookings with unparseable phones are
        rejected with a 400. The resolved customer's canonical phone is
        also written back to the legacy `customer_phone` column so the two
        stay in sync until the legacy column is removed.

        v8 pricing-rules: ``total_amount`` is stamped from a real
        ``compute_quote`` call so the row never has a NULL ``total_amount``.
        Task 176 wires the optimistic-concurrency ``expected_total_amount``
        check on top of this; for now every new booking simply accepts the
        server-computed total. Falls back to ``price_per_hour * hours`` if
        the pricing engine isn't importable yet (defence in depth — engine
        lives in the same epic but tests may stub it out).
        """
        from decimal import ROUND_HALF_UP, Decimal

        from core.customers import UnparseablePhoneError, resolve_customer

        resource = validated_data["resource"]
        try:
            customer = resolve_customer(
                store=resource.store,
                raw_phone=validated_data["customer_phone"],
                name=validated_data.get("customer_name", ""),
            )
        except UnparseablePhoneError as exc:
            raise serializers.ValidationError({"customer_phone": str(exc)}) from None
        validated_data["customer"] = customer
        validated_data["customer_phone"] = customer.phone

        # Freeze the quote on the row. Engine returns base when no rules
        # exist, so existing tests (zero rules configured) keep their
        # baseline of ``price_per_hour * hours``.
        start_at = validated_data["start_time"]
        end_at = validated_data["end_time"]
        try:
            from pricing.engine import compute_quote

            quote = compute_quote(resource, start_at, end_at, customer=customer)
            validated_data["total_amount"] = quote.total_amount
            validated_data["rule_snapshot"] = [li.to_dict() for li in quote.line_items]
        except Exception:
            seconds = int((end_at - start_at).total_seconds())
            hours = (Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.0001"))
            validated_data["total_amount"] = (resource.price_per_hour * hours).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            validated_data["rule_snapshot"] = []

        return super().create(validated_data)


class BookingPatchSerializer(serializers.ModelSerializer):
    """Deserializes PATCH /api/bookings/{id}/ request body (all fields optional)."""

    class Meta:
        model = Booking
        fields = [
            "start_time",
            "end_time",
            "status",
            "customer_name",
            "customer_phone",
        ]

    def validate(self, attrs):
        start = attrs.get("start_time") or (self.instance.start_time if self.instance else None)
        end = attrs.get("end_time") or (self.instance.end_time if self.instance else None)
        if start and end and end <= start:
            raise serializers.ValidationError({"end_time": "end_time must be after start_time."})
        return attrs


# ---------------------------------------------------------------------------
# Conversations & Messages
# ---------------------------------------------------------------------------


class MessageSerializer(serializers.ModelSerializer):
    """Full Message read representation."""

    conversation_id = serializers.IntegerField(source="conversation.id", read_only=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "conversation_id",
            "role",
            "content",
            "tool_call_data",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    """Conversation summary (no messages)."""

    class Meta:
        model = Conversation
        fields = [
            "id",
            "customer_identifier",
            "started_at",
            "status",
            "channel",
        ]
        read_only_fields = ["id", "started_at"]


class ConversationDetailSerializer(ConversationSerializer):
    """Conversation detail including embedded messages."""

    messages = MessageSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ["messages"]


class ConversationCreateSerializer(serializers.ModelSerializer):
    """Deserializes POST /api/conversations/ request body."""

    class Meta:
        model = Conversation
        fields = ["customer_identifier"]
        extra_kwargs = {
            "customer_identifier": {"required": False, "allow_blank": True},
        }


# ---------------------------------------------------------------------------
# Customers (admin)
# ---------------------------------------------------------------------------


class CustomerSummarySerializer(serializers.ModelSerializer):
    """List-view shape: just the columns the admin /customers table renders."""

    class Meta:
        model = Customer
        fields = [
            "id",
            "phone",
            "name",
            "email",
            "locale_pref",
            "tags",
            "total_visits",
            "last_visit_at",
            "created_at",
        ]
        read_only_fields = fields


class CustomerVisitSerializer(serializers.ModelSerializer):
    """One booking row embedded in the customer detail view."""

    resource_name = serializers.CharField(source="resource.name", read_only=True)
    resource_type = serializers.CharField(source="resource.type", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "resource_name",
            "resource_type",
            "start_time",
            "end_time",
            "status",
            "source",
            "created_at",
        ]
        read_only_fields = fields


class CustomerNoteSerializer(serializers.ModelSerializer):
    """A single note, with the author's username flattened for the UI."""

    author_username = serializers.CharField(source="author.username", read_only=True, default=None)

    class Meta:
        model = CustomerNote
        fields = ["id", "body", "author_username", "created_at"]
        read_only_fields = ["id", "author_username", "created_at"]


class CustomerDetailSerializer(CustomerSummarySerializer):
    """Customer detail: profile + recent visits + notes log."""

    visits = serializers.SerializerMethodField()
    notes = CustomerNoteSerializer(many=True, read_only=True)

    class Meta(CustomerSummarySerializer.Meta):
        fields = CustomerSummarySerializer.Meta.fields + ["visits", "notes"]

    def get_visits(self, obj):
        # Most recent 50 bookings, newest first. The signal-maintained
        # counter on Customer makes the full-count query unnecessary here.
        qs = obj.bookings.select_related("resource").order_by("-start_time")[:50]
        return CustomerVisitSerializer(qs, many=True).data


class CustomerNoteCreateSerializer(serializers.ModelSerializer):
    """Deserializes POST /api/admin/customers/{id}/notes/."""

    class Meta:
        model = CustomerNote
        fields = ["body"]


# ---------------------------------------------------------------------------
# QR (One QR engagement)
# ---------------------------------------------------------------------------


class QRActionSerializer(serializers.ModelSerializer):
    """Read/write representation of a single configurable QR chip."""

    class Meta:
        model = QRAction
        fields = [
            "id",
            "kind",
            "label",
            "target_url",
            "position",
            "reward_points",
            "enabled",
        ]
        read_only_fields = ["id"]


class QRActionCreateSerializer(serializers.ModelSerializer):
    """Create payload — `position` is optional; views.py appends to the
    end when omitted."""

    position = serializers.IntegerField(required=False, min_value=0)

    class Meta:
        model = QRAction
        fields = ["kind", "label", "target_url", "position", "reward_points", "enabled"]


class QREventCreateSerializer(serializers.Serializer):
    """Public POST /api/qr/event/ — anonymous-friendly tracking input."""

    slug = serializers.SlugField(required=True)
    action_id = serializers.IntegerField(required=False, allow_null=True)
    kind = serializers.ChoiceField(choices=["scan", "click"])

    def validate(self, attrs):
        if attrs["kind"] == "click" and not attrs.get("action_id"):
            raise serializers.ValidationError({"action_id": "Required for kind='click'."})
        return attrs
