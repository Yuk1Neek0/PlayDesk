"""
PlayDesk campaigns models.

A `Segment` is a saved JSON DSL filter over the store's `Customer` table.
A `Campaign` is a one-shot marketing send against a segment; status moves
forward only (draft -> scheduled -> sending -> sent | cancelled).
A `CampaignRun` is one row per recipient — the audit log of what was
attempted, who succeeded, who failed, and who was skipped (opt-out).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import Customer, Store


class Segment(models.Model):
    """A reusable customer audience defined by a four-key JSON DSL.

    See `backend/campaigns/segments.py::customers_for` for the evaluator
    that compiles `filter` into a store-scoped Django ORM query.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="segments")
    name = models.CharField(max_length=200)
    filter = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["store", "name"]

    def __str__(self) -> str:
        return f"{self.store.name} / {self.name}"


class CampaignStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SCHEDULED = "scheduled", "Scheduled"
    SENDING = "sending", "Sending"
    SENT = "sent", "Sent"
    CANCELLED = "cancelled", "Cancelled"


class Campaign(models.Model):
    """A one-shot marketing send against a Segment.

    `body_template` accepts `{customer.name}` / `{store.name}` placeholders
    rendered at send time. Status transitions are append-only (enforced by
    `runner.send_campaign`); editing past `draft` returns 409 at the view
    layer.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="campaigns")
    name = models.CharField(max_length=200)
    segment = models.ForeignKey(Segment, on_delete=models.PROTECT, related_name="campaigns")
    body_template = models.TextField()
    scheduled_for = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=16,
        choices=CampaignStatus.choices,
        default=CampaignStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    recipient_snapshot_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Campaign {self.pk} – {self.name}"


class CampaignRunStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    SKIPPED_OPTOUT = "skipped_optout", "Skipped (opt-out)"


class CampaignRun(models.Model):
    """One row per recipient. Unique on (campaign, customer) — the DB
    rejects double-sending the same campaign to the same customer."""

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="runs")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="campaign_runs")
    status = models.CharField(
        max_length=16,
        choices=CampaignRunStatus.choices,
        default=CampaignRunStatus.QUEUED,
    )
    outbound_message_id = models.CharField(max_length=100, blank=True)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["campaign", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "customer"],
                name="campaignrun_unique_campaign_customer",
            ),
        ]
        indexes = [
            models.Index(
                fields=["campaign", "status"],
                name="campaignrun_camp_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Run {self.pk} c={self.campaign_id} cust={self.customer_id} [{self.status}]"
