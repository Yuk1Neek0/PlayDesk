"""
Tests for Stripe sandbox deposits (Issue #25).

Stripe SDK calls are mocked throughout — no network, no API key needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import Client, override_settings
from django.utils import timezone


@pytest.fixture()
def store(db):
    from core.models import Store

    return Store.objects.create(name="Stripe Test Store", timezone="UTC", business_hours={})


@pytest.fixture()
def resource(store):
    from core.models import Resource

    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Station Z",
        capacity=4,
        price_per_hour="58.00",
        metadata={},
    )


def _make_booking(resource, status, start_hour):
    from core.models import Booking, BookingSource

    return Booking.objects.create(
        resource=resource,
        customer_name="Mei Lin",
        customer_phone="+86-138-0000-0000",
        start_time=datetime(2026, 7, 5, start_hour, 0, tzinfo=UTC),
        end_time=datetime(2026, 7, 5, start_hour + 2, 0, tzinfo=UTC),
        status=status,
        source=BookingSource.AGENT,
    )


# ---------------------------------------------------------------------------
# create_booking — opens a pending-payment hold
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateBookingDeposit:
    def _input(self, resource, start_hour=14):
        from agent_tools.schemas import CreateBookingInput

        return CreateBookingInput(
            resource_id=resource.pk,
            start_time=datetime(2026, 7, 1, start_hour, 0, tzinfo=UTC),
            duration_minutes=120,
            customer_name="Mei Lin",
            customer_phone="+86-138-0000-0000",
        )

    def test_booking_is_created_pending_payment(self, resource):
        from agent_tools.schemas import CreateBookingSuccess
        from agent_tools.tools import create_booking
        from core.models import Booking, BookingStatus

        out = create_booking(self._input(resource))

        assert isinstance(out.result, CreateBookingSuccess)
        booking = Booking.objects.get(pk=out.result.booking_id)
        assert booking.status == BookingStatus.PENDING_PAYMENT

    def test_opens_a_checkout_session_for_the_booking(self, resource):
        from agent_tools.tools import create_booking

        with mock.patch("core.payments.create_checkout_session") as create_session:
            out = create_booking(self._input(resource, start_hour=16))

        assert create_session.call_count == 1
        booking_arg = create_session.call_args.args[0]
        assert booking_arg.pk == out.result.booking_id


# ---------------------------------------------------------------------------
# create_checkout_session — the Stripe gateway
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckoutSession:
    def test_no_op_when_stripe_is_not_configured(self, resource):
        from core.payments import create_checkout_session

        booking = _make_booking(resource, "pending_payment", 10)
        # Default settings leave STRIPE_SECRET_KEY empty.
        assert create_checkout_session(booking) is None

    def test_session_carries_the_booking_id_in_metadata(self, resource):
        from core.payments import create_checkout_session

        booking = _make_booking(resource, "pending_payment", 12)
        fake_session = mock.Mock(url="https://checkout.stripe.test/abc")

        with (
            override_settings(STRIPE_SECRET_KEY="sk_test_dummy"),
            mock.patch("stripe.checkout.Session.create", return_value=fake_session) as create,
        ):
            url = create_checkout_session(booking)

        assert url == "https://checkout.stripe.test/abc"
        kwargs = create.call_args.kwargs
        assert kwargs["mode"] == "payment"
        assert kwargs["metadata"] == {"booking_id": str(booking.pk)}


# ---------------------------------------------------------------------------
# Stripe webhook — confirms a paid booking
# ---------------------------------------------------------------------------


def _completed_event(booking_id) -> dict:
    return {
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"booking_id": str(booking_id)}}},
    }


@pytest.mark.django_db
class TestStripeWebhook:
    def _post(self):
        return Client().post("/api/webhooks/stripe/", data=b"{}", content_type="application/json")

    def test_checkout_completed_confirms_the_booking(self, resource):
        from core.models import BookingStatus

        booking = _make_booking(resource, BookingStatus.PENDING_PAYMENT, 10)
        with mock.patch(
            "core.payments.verify_webhook_event", return_value=_completed_event(booking.pk)
        ):
            resp = self._post()

        assert resp.status_code == 200
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED

    def test_other_event_types_are_ignored(self, resource):
        from core.models import BookingStatus

        booking = _make_booking(resource, BookingStatus.PENDING_PAYMENT, 12)
        event = {"type": "payment_intent.created", "data": {"object": {}}}
        with mock.patch("core.payments.verify_webhook_event", return_value=event):
            resp = self._post()

        assert resp.status_code == 200
        booking.refresh_from_db()
        assert booking.status == BookingStatus.PENDING_PAYMENT

    def test_invalid_signature_returns_400(self, db):
        with mock.patch(
            "core.payments.verify_webhook_event", side_effect=ValueError("bad signature")
        ):
            resp = self._post()

        assert resp.status_code == 400

    def test_is_idempotent_for_an_already_confirmed_booking(self, resource):
        from core.models import BookingStatus

        booking = _make_booking(resource, BookingStatus.CONFIRMED, 14)
        with mock.patch(
            "core.payments.verify_webhook_event", return_value=_completed_event(booking.pk)
        ):
            resp = self._post()

        assert resp.status_code == 200
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED


# ---------------------------------------------------------------------------
# expire_holds — reaps stale pending-payment holds
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestExpireHolds:
    def test_stale_pending_payment_hold_is_expired(self, resource):
        from core.models import Booking, BookingStatus

        booking = _make_booking(resource, BookingStatus.PENDING_PAYMENT, 10)
        Booking.objects.filter(pk=booking.pk).update(created_at=timezone.now() - timedelta(hours=2))

        call_command("expire_holds")

        assert not Booking.objects.filter(pk=booking.pk).exists()

    def test_recent_hold_and_confirmed_booking_survive(self, resource):
        from core.models import Booking, BookingStatus

        recent_hold = _make_booking(resource, BookingStatus.PENDING_PAYMENT, 12)
        confirmed = _make_booking(resource, BookingStatus.CONFIRMED, 14)
        # Backdate the confirmed booking too — status, not age, must protect it.
        Booking.objects.filter(pk=confirmed.pk).update(
            created_at=timezone.now() - timedelta(hours=5)
        )

        call_command("expire_holds")

        assert Booking.objects.filter(pk=recent_hold.pk).exists()
        assert Booking.objects.filter(pk=confirmed.pk).exists()
