"""Receipts + v5 dashboard tiles + /admin/payments/ ledger (task #185)."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest import mock

import pytest
from django.core import mail
from django.test import Client, override_settings

from billing.models import Payment, PaymentKind, PaymentRowStatus


@pytest.mark.django_db
class TestPaymentReceipt:
    def test_webhook_succeeded_dispatches_sms_and_email(self, store, booking):
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("24.00"),
            currency="USD",
            stripe_payment_intent_id="pi_recpt",
        )
        with (
            override_settings(STRIPE_WEBHOOK_SECRET=""),
            mock.patch("billing.receipts._enqueue") as enqueue,
        ):
            Client().post(
                "/api/stripe/webhook/",
                data=json.dumps(
                    {
                        "id": "evt_recpt",
                        "type": "payment_intent.succeeded",
                        "data": {"object": {"id": "pi_recpt", "latest_charge": "ch_recpt"}},
                    }
                ),
                content_type="application/json",
            )
        enqueue.assert_called_once()
        # Customer has email → Django mail.outbox gets a message.
        assert any(
            "Payment receipt" in m.subject or "payment receipt" in m.subject.lower()
            for m in mail.outbox
        )


@pytest.mark.django_db
class TestRefundReceipt:
    def test_webhook_refunded_dispatches_sms(self, store, booking):
        from core.models import PaymentStatus

        booking.payment_status = PaymentStatus.DEPOSIT_PAID
        booking.deposit_amount = Decimal("24.00")
        booking.save()
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("24.00"),
            currency="USD",
            stripe_payment_intent_id="pi_refundr",
            stripe_charge_id="ch_refundr",
            status=PaymentRowStatus.SUCCEEDED,
        )
        with (
            override_settings(STRIPE_WEBHOOK_SECRET=""),
            mock.patch("billing.receipts._enqueue") as enqueue,
        ):
            Client().post(
                "/api/stripe/webhook/",
                data=json.dumps(
                    {
                        "id": "evt_refr",
                        "type": "charge.refunded",
                        "data": {"object": {"id": "ch_refundr", "amount_refunded": 2400}},
                    }
                ),
                content_type="application/json",
            )
        enqueue.assert_called_once()


@pytest.mark.django_db
class TestDashboardTiles:
    def test_revenue_and_refunds_mtd(self, store, booking):
        # Two successful deposits + one refund, all this month.
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("24.00"),
            currency="USD",
            status=PaymentRowStatus.SUCCEEDED,
        )
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.BALANCE,
            amount=Decimal("56.00"),
            currency="USD",
            status=PaymentRowStatus.SUCCEEDED,
        )
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.REFUND,
            amount=Decimal("-10.00"),
            currency="USD",
            status=PaymentRowStatus.SUCCEEDED,
        )
        resp = Client().get(
            "/api/admin/metrics/business/",
            HTTP_X_PD_STORE_SLUG=store.slug,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["revenue_mtd"]["amount"] == "80.00"
        assert body["refunds_mtd"]["amount"] == "10.00"


@pytest.mark.django_db
class TestPaymentLedger:
    def test_lists_payments_filtered(self, store, booking):
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("24.00"),
            currency="USD",
            status=PaymentRowStatus.SUCCEEDED,
        )
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.REFUND,
            amount=Decimal("-10.00"),
            currency="USD",
            status=PaymentRowStatus.SUCCEEDED,
        )
        resp = Client().get(
            "/api/admin/payments/?kind=refund",
            HTTP_X_PD_STORE_SLUG=store.slug,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["results"][0]["kind"] == "refund"
