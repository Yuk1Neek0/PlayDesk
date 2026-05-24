"""Outbound messaging models.

`OutboundMessage` is the queue: every confirmation, reminder, no-show
recovery, thank-you, or campaign blast lives here until the
`send_outbound` cron command picks it up. The `(status, scheduled_for)`
composite index keeps the sender's hot query a single range scan.

Quiet-hours fields live on `Store` (not on each `OutboundMessage`) so a
store-wide policy change applies to all future sends without rewriting
already-queued rows.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class OutboundChannel(models.TextChoices):
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"
    WEB_CHAT = "web_chat", "Web chat"


class OutboundStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class OutboundMessage(models.Model):
    """One pending or historical outbound message.

    `reference` is a free-form correlation key (e.g. `"booking:42:reminder_24h"`)
    that lets the booking-lifecycle signals stay idempotent — re-firing on the
    same booking won't double-enqueue.
    """

    customer = models.ForeignKey(
        "core.Customer",
        on_delete=models.CASCADE,
        related_name="outbound_messages",
    )
    channel = models.CharField(
        max_length=16,
        choices=OutboundChannel.choices,
        default=OutboundChannel.SMS,
    )
    template_key = models.CharField(max_length=64)
    body = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=OutboundStatus.choices,
        default=OutboundStatus.QUEUED,
    )
    scheduled_for = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    reference = models.CharField(max_length=100, blank=True)
    provider_message_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # Sender hot path: status='queued' AND scheduled_for <= now().
            models.Index(fields=["status", "scheduled_for"], name="outbound_status_sched_idx"),
            # Per-customer log query: newest-first by created_at.
            models.Index(fields=["customer", "-created_at"], name="outbound_customer_created_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"OutboundMessage {self.pk} [{self.template_key} → {self.customer_id} / {self.status}]"
        )
