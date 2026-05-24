"""Cancel→refund + charge-balance + sweep cron (task #184)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone

from billing.models import Payment, PaymentKind
from billing.views import cancel_booking_with_refund, sweep_pending_payments


def _paid_booking(resource, customer, deposit: Decimal, hours_ahead: float):
    from core.models import Booking, BookingStatus, PaymentStatus

    start = datetime.now(tz=UTC) + timedelta(hours=hours_ahead)
    return Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        start_time=start,
        end_time=start + timedelta(hours=2),
        status=BookingStatus.CONFIRMED,
        payment_status=PaymentStatus.DEPOSIT_PAID,
        deposit_amount=deposit,
        payment_intent_id="pi_test_x",
    )


@pytest.mark.django_db
class TestCancelRefund:
    def test_full_refund_window(self, store, resource, customer):
        booking = _paid_booking(resource, customer, Decimal("24.00"), 72)
        with mock.patch("stripe.Refund.create") as refund:
            result = cancel_booking_with_refund(booking)
        assert result["refund_amount"] == "24.00"
        # Stripe call skipped in test mode without keys; payment row succeeded.
        refund.assert_not_called()
        assert Payment.objects.filter(kind=PaymentKind.REFUND).count() == 1

    def test_partial_refund(self, store, resource, customer):
        booking = _paid_booking(resource, customer, Decimal("24.00"), 36)
        result = cancel_booking_with_refund(booking)
        assert result["refund_amount"] == "12.00"

    def test_no_refund_inside_zero_window(self, store, resource, customer):
        booking = _paid_booking(resource, customer, Decimal("24.00"), 1)
        result = cancel_booking_with_refund(booking)
        assert result["refund_amount"] == "0.00"
        assert result["refunded"] is False

    def test_calls_stripe_when_configured(self, store, resource, customer):
        booking = _paid_booking(resource, customer, Decimal("24.00"), 72)
        with (
            override_settings(STRIPE_SECRET_KEY="sk_test_x"),
            mock.patch("stripe.Refund.create") as refund,
        ):
            cancel_booking_with_refund(booking)
        refund.assert_called_once_with(payment_intent="pi_test_x", amount=2400)


@pytest.mark.django_db
class TestChargeBalance:
    def test_creates_checkout_session(self, store, resource, customer):
        from core.models import Booking, BookingStatus, PaymentStatus

        booking = Booking.objects.create(
            resource=resource,
            customer=customer,
            customer_name=customer.name,
            customer_phone=customer.phone,
            start_time=datetime(2026, 8, 1, 14, 0, tzinfo=UTC),
            end_time=datetime(2026, 8, 1, 16, 0, tzinfo=UTC),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.DEPOSIT_PAID,
            deposit_amount=Decimal("24.00"),
        )
        store.stripe_account_id = "acct_x"
        store.save()
        fake_session = mock.Mock(
            id="cs_x",
            url="https://checkout.stripe.test/x",
            payment_intent="pi_balance",
        )
        with (
            override_settings(STRIPE_SECRET_KEY="sk_test_x"),
            mock.patch("stripe.checkout.Session.create", return_value=fake_session) as create,
        ):
            resp = Client().post(
                f"/api/admin/bookings/{booking.pk}/charge-balance/",
                content_type="application/json",
                HTTP_X_PD_STORE_SLUG=store.slug,
            )
        assert resp.status_code == 200
        # $80 total - $24 deposit = $56 balance.
        assert resp.json()["balance_amount"] == "56.00"
        create.assert_called_once()
        assert Payment.objects.filter(kind=PaymentKind.BALANCE).count() == 1

    def test_rejects_when_paid_in_full(self, store, resource, customer):
        from core.models import Booking, BookingStatus, PaymentStatus

        booking = Booking.objects.create(
            resource=resource,
            customer=customer,
            customer_name=customer.name,
            customer_phone=customer.phone,
            start_time=datetime(2026, 8, 1, 14, 0, tzinfo=UTC),
            end_time=datetime(2026, 8, 1, 16, 0, tzinfo=UTC),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.PAID_IN_FULL,
            deposit_amount=Decimal("80.00"),
        )
        resp = Client().post(
            f"/api/admin/bookings/{booking.pk}/charge-balance/",
            content_type="application/json",
            HTTP_X_PD_STORE_SLUG=store.slug,
        )
        assert resp.status_code == 400


@pytest.mark.django_db
class TestSweepPendingPayments:
    def _pending(self, resource, age_minutes: int):
        from core.models import Booking, BookingStatus, PaymentStatus

        start = datetime(2026, 8, 1, 14, 0, tzinfo=UTC)
        b = Booking.objects.create(
            resource=resource,
            customer_name="x",
            customer_phone="+12025550000",
            start_time=start,
            end_time=start + timedelta(hours=1),
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.PENDING_PAYMENT,
            deposit_amount=Decimal("10.00"),
        )
        Booking.objects.filter(pk=b.pk).update(
            created_at=timezone.now() - timedelta(minutes=age_minutes)
        )
        return b

    def test_sweeps_stale_holds(self, resource):
        b = self._pending(resource, age_minutes=30)
        n = sweep_pending_payments()
        b.refresh_from_db()
        from core.models import BookingStatus, PaymentStatus

        assert n == 1
        assert b.status == BookingStatus.CANCELLED
        assert b.payment_status == PaymentStatus.NOT_REQUIRED

    def test_leaves_fresh_holds_alone(self, resource):
        b = self._pending(resource, age_minutes=2)
        n = sweep_pending_payments()
        b.refresh_from_db()
        from core.models import PaymentStatus

        assert n == 0
        assert b.payment_status == PaymentStatus.PENDING_PAYMENT

    def test_management_command(self, resource):
        self._pending(resource, age_minutes=30)
        call_command("sweep_pending_payments")
