"""Webhook receiver tests (task #183).

Stripe's signature verifier is mocked out — the test posts a JSON body
directly and verifies the dispatcher + handlers + idempotency.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest import mock

import pytest
from django.test import Client, override_settings

from billing.models import Payment, PaymentKind, PaymentRowStatus, WebhookEvent
from core.models import BookingStatus, PaymentStatus


def _post(payload: dict):
    return Client().post(
        "/api/stripe/webhook/",
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.mark.django_db
class TestSignatureVerification:
    def test_bad_signature_returns_400(self):
        with (
            override_settings(STRIPE_WEBHOOK_SECRET="whsec_x"),
            mock.patch(
                "stripe.Webhook.construct_event",
                side_effect=ValueError("bad sig"),
            ),
        ):
            resp = _post({"id": "evt_1", "type": "payment_intent.succeeded"})
        assert resp.status_code == 400

    def test_no_secret_skips_verification(self):
        # When STRIPE_WEBHOOK_SECRET is empty, payload is parsed directly.
        with override_settings(STRIPE_WEBHOOK_SECRET=""):
            resp = _post({"id": "evt_noverify", "type": "noop.event"})
        assert resp.status_code == 200


@pytest.mark.django_db
class TestIdempotency:
    def test_replay_is_noop(self, store, booking):
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("24.00"),
            currency="USD",
            stripe_payment_intent_id="pi_xx",
        )
        event = {
            "id": "evt_idem",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_xx", "latest_charge": "ch_xx"}},
        }
        with override_settings(STRIPE_WEBHOOK_SECRET=""):
            resp1 = _post(event)
            resp2 = _post(event)
        assert resp1.status_code == resp2.status_code == 200
        # Handler ran exactly once: only one WebhookEvent exists.
        assert WebhookEvent.objects.filter(stripe_event_id="evt_idem").count() == 1


@pytest.mark.django_db
class TestPaymentIntentSucceeded:
    def test_deposit_flips_booking_to_confirmed(self, store, booking):
        booking.payment_status = PaymentStatus.PENDING_PAYMENT
        booking.status = BookingStatus.PENDING
        booking.save()
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("24.00"),
            currency="USD",
            stripe_payment_intent_id="pi_dep",
        )
        with override_settings(STRIPE_WEBHOOK_SECRET=""):
            resp = _post(
                {
                    "id": "evt_dep",
                    "type": "payment_intent.succeeded",
                    "data": {"object": {"id": "pi_dep", "latest_charge": "ch_dep"}},
                }
            )
        assert resp.status_code == 200
        booking.refresh_from_db()
        assert booking.payment_status == PaymentStatus.DEPOSIT_PAID
        assert booking.status == BookingStatus.CONFIRMED
        p = Payment.objects.get(stripe_payment_intent_id="pi_dep")
        assert p.status == PaymentRowStatus.SUCCEEDED
        assert p.stripe_charge_id == "ch_dep"


@pytest.mark.django_db
class TestPaymentIntentFailed:
    def test_marks_payment_failed_booking_stays_pending(self, store, booking):
        booking.payment_status = PaymentStatus.PENDING_PAYMENT
        booking.save()
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("24.00"),
            currency="USD",
            stripe_payment_intent_id="pi_fail",
        )
        with override_settings(STRIPE_WEBHOOK_SECRET=""):
            _post(
                {
                    "id": "evt_fail",
                    "type": "payment_intent.payment_failed",
                    "data": {"object": {"id": "pi_fail"}},
                }
            )
        booking.refresh_from_db()
        assert booking.payment_status == PaymentStatus.PENDING_PAYMENT
        p = Payment.objects.get(stripe_payment_intent_id="pi_fail")
        assert p.status == PaymentRowStatus.FAILED


@pytest.mark.django_db
class TestChargeRefunded:
    def test_creates_refund_row_and_flips_status(self, store, booking):
        booking.payment_status = PaymentStatus.DEPOSIT_PAID
        booking.deposit_amount = Decimal("24.00")
        booking.save()
        Payment.objects.create(
            store=store,
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            amount=Decimal("24.00"),
            currency="USD",
            stripe_payment_intent_id="pi_r",
            stripe_charge_id="ch_r",
            status=PaymentRowStatus.SUCCEEDED,
        )
        with override_settings(STRIPE_WEBHOOK_SECRET=""):
            _post(
                {
                    "id": "evt_refund",
                    "type": "charge.refunded",
                    "data": {"object": {"id": "ch_r", "amount_refunded": 2400}},
                }
            )
        booking.refresh_from_db()
        assert booking.payment_status == PaymentStatus.REFUNDED
        refund = Payment.objects.get(kind=PaymentKind.REFUND)
        assert refund.amount == Decimal("-24.00")


@pytest.mark.django_db
class TestAccountUpdated:
    def test_updates_store_charges_enabled(self, store):
        store.stripe_account_id = "acct_au"
        store.save()
        with override_settings(STRIPE_WEBHOOK_SECRET=""):
            _post(
                {
                    "id": "evt_au",
                    "type": "account.updated",
                    "data": {"object": {"id": "acct_au", "charges_enabled": True}},
                }
            )
        store.refresh_from_db()
        assert store.stripe_charges_enabled is True
