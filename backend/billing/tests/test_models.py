"""Tests for billing.models — Payment + WebhookEvent + Booking.balance_amount."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError

from billing.models import Payment, PaymentKind, PaymentRowStatus, WebhookEvent


@pytest.mark.django_db
class TestPaymentModel:
    def test_create_with_defaults(self, store, booking):
        p = Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("24.00"),
            currency="USD",
        )
        assert p.status == PaymentRowStatus.PENDING
        assert p.metadata == {}
        assert p.created_at is not None

    def test_stripe_event_id_unique(self, store, booking):
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("24.00"),
            currency="USD",
            stripe_event_id="evt_dup",
        )
        with pytest.raises(IntegrityError):
            Payment.objects.create(
                store=store,
                booking=booking,
                kind=PaymentKind.DEPOSIT,
                amount=Decimal("10.00"),
                currency="USD",
                stripe_event_id="evt_dup",
            )

    def test_multiple_null_event_ids_allowed(self, store, booking):
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("1.00"),
            currency="USD",
        )
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("2.00"),
            currency="USD",
        )
        assert Payment.objects.count() == 2


@pytest.mark.django_db
class TestWebhookEventModel:
    def test_create_and_uniqueness(self):
        WebhookEvent.objects.create(
            stripe_event_id="evt_1",
            event_type="payment_intent.succeeded",
            payload={"foo": "bar"},
        )
        with pytest.raises(IntegrityError):
            WebhookEvent.objects.create(
                stripe_event_id="evt_1",
                event_type="charge.refunded",
                payload={},
            )


@pytest.mark.django_db
class TestBalanceAmount:
    def test_no_total_falls_back_to_hourly(self, booking):
        # 2 hours @ $40/hr = $80; deposit_amount default $0; balance = $80
        booking.deposit_amount = Decimal("0.00")
        booking.save()
        assert booking.balance_amount == Decimal("80.00")

    def test_with_deposit(self, booking):
        booking.deposit_amount = Decimal("24.00")
        booking.save()
        assert booking.balance_amount == Decimal("56.00")
