"""Billing models — payment ledger and webhook audit log.

`Payment` is the canonical ledger row: one per deposit, balance charge,
refund, or manual adjustment. The `stripe_event_id` unique constraint
gives us idempotency for free — replaying a Stripe webhook event is
a no-op because the second `INSERT` violates the unique index.

`WebhookEvent` is a *separate* universal audit table because not every
Stripe event creates a Payment row (e.g., `account.updated`). Storing the
raw payload lets us replay manually after a handler crash.
"""

from __future__ import annotations

from django.db import models

from core.models import Booking, Store


class PaymentKind(models.TextChoices):
    DEPOSIT = "deposit", "Deposit"
    BALANCE = "balance", "Balance"
    REFUND = "refund", "Refund"
    ADJUSTMENT = "adjustment", "Adjustment"


class PaymentRowStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"


class Payment(models.Model):
    """One ledger row per deposit / balance charge / refund.

    `amount` is signed: refunds are negative so a running SUM
    aggregates correctly. `stripe_event_id` is unique-but-nullable —
    Postgres allows multiple NULLs but enforces uniqueness on real
    values, which gives webhook idempotency without a sentinel.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="payments")
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")
    kind = models.CharField(max_length=16, choices=PaymentKind.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=16,
        choices=PaymentRowStatus.choices,
        default=PaymentRowStatus.PENDING,
    )
    stripe_payment_intent_id = models.CharField(
        max_length=128, null=True, blank=True, db_index=True
    )
    stripe_charge_id = models.CharField(max_length=128, null=True, blank=True)
    stripe_event_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["store", "status", "-created_at"],
                name="payment_store_status_ts_idx",
            ),
            models.Index(
                fields=["stripe_charge_id"],
                name="payment_charge_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Payment {self.pk} {self.kind} {self.amount} {self.currency}"


class WebhookEvent(models.Model):
    """Raw Stripe webhook audit log — one row per delivery.

    Persisted before the handler runs so a handler crash leaves the
    event recoverable. The `stripe_event_id` unique constraint blocks
    duplicate inserts (Stripe retries aggressively), giving the
    webhook receiver idempotency before any handler logic runs.
    """

    stripe_event_id = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=64)
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["event_type", "-created_at"],
                name="webhookevent_type_ts_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"WebhookEvent {self.stripe_event_id} ({self.event_type})"
