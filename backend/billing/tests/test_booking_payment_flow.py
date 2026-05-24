"""Booking-create wiring + PaymentIntent flow (task #182)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest import mock

import pytest
from django.test import Client, override_settings


def _create_booking(client, store, resource, start_hour=14):
    body = {
        "resource_id": resource.id,
        "customer_name": "Mei Lin",
        "customer_phone": "+12025550000",
        "start_time": datetime(2026, 8, 1, start_hour, 0, tzinfo=UTC).isoformat(),
        "end_time": datetime(2026, 8, 1, start_hour + 2, 0, tzinfo=UTC).isoformat(),
    }
    return client.post(
        "/api/bookings/",
        data=body,
        content_type="application/json",
        HTTP_X_PD_STORE_SLUG=store.slug,
    )


@pytest.mark.django_db
class TestNoDepositFlow:
    def test_skips_stripe_when_deposit_mode_none(self, store, resource):
        store.deposit_mode = "none"
        store.save()
        with mock.patch("stripe.PaymentIntent.create") as create:
            resp = _create_booking(Client(), store, resource)
        assert resp.status_code == 201
        body = resp.json()
        assert "requires_payment" not in body
        assert body["payment_status"] == "not_required"
        create.assert_not_called()


@pytest.mark.django_db
class TestPercentageDepositFlow:
    def test_creates_payment_intent(self, store, resource):
        store.deposit_mode = "percentage"
        store.deposit_value = Decimal("30")
        store.stripe_account_id = "acct_x"
        store.stripe_charges_enabled = True
        store.save()

        fake_intent = mock.Mock(id="pi_123", client_secret="pi_123_secret_xyz")
        with (
            override_settings(STRIPE_SECRET_KEY="sk_test_x"),
            mock.patch("stripe.PaymentIntent.create", return_value=fake_intent) as create,
        ):
            resp = _create_booking(Client(), store, resource)

        assert resp.status_code == 201
        body = resp.json()
        # $40/hr * 2h * 30% = $24.00
        assert body["requires_payment"] is True
        assert body["deposit_amount"] == "24.00"
        assert body["client_secret"] == "pi_123_secret_xyz"
        assert body["payment_status"] == "pending_payment"

        create.assert_called_once()
        kwargs = create.call_args.kwargs
        assert kwargs["amount"] == 2400  # cents
        assert kwargs["currency"] == "usd"
        assert kwargs["transfer_data"]["destination"] == "acct_x"


@pytest.mark.django_db
class TestResourceOverrideFlow:
    def test_resource_override_wins(self, store, resource):
        store.deposit_mode = "percentage"
        store.deposit_value = Decimal("30")
        store.save()
        resource.deposit_override_mode = "fixed"
        resource.deposit_override_value = Decimal("50.00")
        resource.save()

        fake_intent = mock.Mock(id="pi_o", client_secret="pi_o_secret")
        with (
            override_settings(STRIPE_SECRET_KEY="sk_test_x"),
            mock.patch("stripe.PaymentIntent.create", return_value=fake_intent),
        ):
            resp = _create_booking(Client(), store, resource, start_hour=10)

        assert resp.json()["deposit_amount"] == "50.00"


@pytest.mark.django_db
class TestPaymentStatusEndpoint:
    def test_returns_status(self, store, resource):
        from core.models import Booking, BookingStatus, PaymentStatus

        b = Booking.objects.create(
            resource=resource,
            customer_name="x",
            customer_phone="+12025551111",
            start_time=datetime(2026, 8, 1, 14, 0, tzinfo=UTC),
            end_time=datetime(2026, 8, 1, 16, 0, tzinfo=UTC),
            status=BookingStatus.PENDING,
            payment_status=PaymentStatus.PENDING_PAYMENT,
        )
        resp = Client().get(f"/api/bookings/{b.pk}/payment-status/")
        assert resp.status_code == 200
        assert resp.json() == {
            "payment_status": "pending_payment",
            "status": "pending",
        }
