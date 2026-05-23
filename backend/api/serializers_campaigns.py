"""DRF serializers for the campaigns admin endpoints."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from campaigns.models import Campaign, CampaignRun, Segment

ALLOWED_SEGMENT_KEYS = {
    "tags_include",
    "min_total_visits",
    "last_visit_within_days",
    "locale_pref",
}


class SegmentSerializer(serializers.ModelSerializer):
    # The queryset is resolved lazily in __init__ to keep this module import-
    # light (Store lives in core.models which pulls in pgvector). Mark the
    # field read_only=False explicitly so DRF doesn't refuse to construct it
    # without a queryset at class-evaluation time.
    store_id = serializers.PrimaryKeyRelatedField(source="store", read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = Segment
        fields = [
            "id",
            "store_id",
            "name",
            "filter",
            "created_by_username",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "created_by_username"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Late import keeps this file import-light.
        from core.models import Store

        # Rebind store_id as writable now that we can supply a queryset.
        self.fields["store_id"] = serializers.PrimaryKeyRelatedField(
            source="store", queryset=Store.objects.all()
        )

    def validate_filter(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("filter must be a JSON object")
        # Unknown keys are tolerated by the evaluator but rejected at write
        # time so staff catch typos before save.
        unknown = set(value) - ALLOWED_SEGMENT_KEYS
        if unknown:
            raise serializers.ValidationError(f"unknown filter keys: {sorted(unknown)}")
        return value


class CampaignSerializer(serializers.ModelSerializer):
    # See SegmentSerializer.store_id for why this is bound lazily.
    store_id = serializers.PrimaryKeyRelatedField(source="store", read_only=True)
    segment_id = serializers.PrimaryKeyRelatedField(
        source="segment", queryset=Segment.objects.all()
    )
    segment_name = serializers.CharField(source="segment.name", read_only=True)
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True, allow_null=True, default=None
    )
    sent_by_username = serializers.CharField(
        source="sent_by.username", read_only=True, allow_null=True, default=None
    )

    class Meta:
        model = Campaign
        fields = [
            "id",
            "store_id",
            "name",
            "segment_id",
            "segment_name",
            "body_template",
            "scheduled_for",
            "status",
            "sent_at",
            "recipient_snapshot_count",
            "created_by_username",
            "sent_by_username",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "sent_at",
            "recipient_snapshot_count",
            "created_by_username",
            "sent_by_username",
            "segment_name",
            "created_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.models import Store

        self.fields["store_id"] = serializers.PrimaryKeyRelatedField(
            source="store", queryset=Store.objects.all()
        )

    def validate_body_template(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("body_template must not be empty")
        return value

    def validate(self, attrs):
        # On create, reject past `scheduled_for`. On update, allow it (drafts
        # may legitimately keep an old scheduled_for while being edited).
        if self.instance is None:
            scheduled_for = attrs.get("scheduled_for")
            if scheduled_for and scheduled_for < timezone.now():
                # Allow a tiny grace window so "now" defaults don't trip.
                from datetime import timedelta

                if scheduled_for < timezone.now() - timedelta(minutes=1):
                    raise serializers.ValidationError({"scheduled_for": "must not be in the past"})
        return attrs


class CampaignRunSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)

    class Meta:
        model = CampaignRun
        fields = [
            "id",
            "customer",
            "customer_name",
            "customer_phone",
            "status",
            "outbound_message_id",
            "failure_reason",
            "created_at",
            "sent_at",
        ]
        read_only_fields = fields


class SegmentPreviewSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    sample = serializers.ListField(child=serializers.DictField())
