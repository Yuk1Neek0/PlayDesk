"""
DRF serializers for the PlayDesk REST API.

Mirrors the OpenAPI schema definitions in docs/contracts/openapi.yaml.
"""

from rest_framework import serializers

from core.models import Booking, Conversation, Customer, CustomerNote, Message, Resource

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
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


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
        """
        from core.customers import UnparseablePhoneError, resolve_customer

        resource = validated_data["resource"]
        try:
            customer = resolve_customer(
                store=resource.store,
                raw_phone=validated_data["customer_phone"],
                name=validated_data.get("customer_name", ""),
            )
        except UnparseablePhoneError as exc:
            raise serializers.ValidationError({"customer_phone": str(exc)})
        validated_data["customer"] = customer
        validated_data["customer_phone"] = customer.phone
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
