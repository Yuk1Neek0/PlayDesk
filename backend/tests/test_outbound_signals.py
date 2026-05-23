"""Tests for outbound booking signals + STOP-handling on inbound adapter."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from agent.channels.twilio_sms import TwilioSmsAdapter
from core.models import Booking, BookingSource, BookingStatus, Customer, Resource, Store
from outbound.models import OutboundMessage, OutboundStatus


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Signal Store", timezone="UTC", business_hours={})


@pytest.fixture()
def resource(store):
    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 #1",
        capacity=4,
        price_per_hour="40.00",
        metadata={},
    )


@pytest.fixture()
def customer(store):
    return Customer.objects.create(
        store=store, phone="+14165550111", name="Alice", locale_pref="en"
    )


def _future_booking(resource, customer, *, hours_ahead: int = 48) -> Booking:
    start = timezone.now() + timedelta(hours=hours_ahead)
    return Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        start_time=start,
        end_time=start + timedelta(hours=1),
        status=BookingStatus.CONFIRMED,
        source=BookingSource.MANUAL,
    )


@pytest.mark.django_db(transaction=True)
def test_create_future_booking_enqueues_confirmation_and_reminder(resource, customer):
    booking = _future_booking(resource, customer, hours_ahead=48)
    rows = list(OutboundMessage.objects.filter(customer=customer).order_by("template_key"))
    assert len(rows) == 2
    keys = {r.template_key for r in rows}
    assert keys == {"booking_confirmation", "reminder_24h"}
    confirm = next(r for r in rows if r.template_key == "booking_confirmation")
    reminder = next(r for r in rows if r.template_key == "reminder_24h")
    assert confirm.reference == f"booking:{booking.id}:confirm"
    assert reminder.reference == f"booking:{booking.id}:reminder_24h"
    # Reminder is exactly 24h before start.
    assert reminder.scheduled_for == booking.start_time - timedelta(hours=24)


@pytest.mark.django_db(transaction=True)
def test_create_near_term_booking_only_enqueues_confirmation(resource, customer):
    """Booking starts in 1h → reminder_24h is in the past, skip it."""
    booking = _future_booking(resource, customer, hours_ahead=1)
    rows = list(OutboundMessage.objects.filter(customer=customer))
    assert len(rows) == 1
    assert rows[0].template_key == "booking_confirmation"
    assert rows[0].reference == f"booking:{booking.id}:confirm"


@pytest.mark.django_db(transaction=True)
def test_status_transition_to_no_show_enqueues_followup(resource, customer):
    booking = _future_booking(resource, customer)
    assert OutboundMessage.objects.filter(template_key="no_show_followup").count() == 0
    booking.status = "no_show"
    booking.save()
    rows = list(OutboundMessage.objects.filter(template_key="no_show_followup"))
    assert len(rows) == 1
    assert rows[0].reference == f"booking:{booking.id}:no_show"


@pytest.mark.django_db(transaction=True)
def test_status_transition_to_completed_enqueues_thank_you(resource, customer):
    booking = _future_booking(resource, customer)
    booking.status = "completed"
    booking.save()
    rows = list(OutboundMessage.objects.filter(template_key="booking_thank_you"))
    assert len(rows) == 1
    assert rows[0].reference == f"booking:{booking.id}:thank_you"


@pytest.mark.django_db(transaction=True)
def test_status_transition_to_cancelled_cancels_queued_rows(resource, customer):
    booking = _future_booking(resource, customer, hours_ahead=48)
    # Confirmation + reminder are both queued.
    assert OutboundMessage.objects.filter(status=OutboundStatus.QUEUED).count() == 2

    booking.status = BookingStatus.CANCELLED
    booking.save()
    queued = OutboundMessage.objects.filter(
        reference__startswith=f"booking:{booking.id}:",
        status=OutboundStatus.QUEUED,
    ).count()
    cancelled = OutboundMessage.objects.filter(
        reference__startswith=f"booking:{booking.id}:",
        status=OutboundStatus.CANCELLED,
    ).count()
    assert queued == 0
    assert cancelled == 2


@pytest.mark.django_db(transaction=True)
def test_cancellation_cascade_leaves_sent_rows_alone(resource, customer):
    booking = _future_booking(resource, customer, hours_ahead=48)
    # Mark the confirmation as already sent.
    confirm = OutboundMessage.objects.get(template_key="booking_confirmation", customer=customer)
    confirm.status = OutboundStatus.SENT
    confirm.sent_at = timezone.now()
    confirm.save()

    booking.status = BookingStatus.CANCELLED
    booking.save()

    confirm.refresh_from_db()
    assert confirm.status == OutboundStatus.SENT  # still sent
    reminder = OutboundMessage.objects.get(template_key="reminder_24h", customer=customer)
    assert reminder.status == OutboundStatus.CANCELLED


@pytest.mark.django_db(transaction=True)
def test_null_customer_booking_does_not_crash(resource):
    """A legacy booking without a customer FK must not crash the signal."""
    start = timezone.now() + timedelta(hours=48)
    Booking.objects.create(
        resource=resource,
        customer=None,
        customer_name="Legacy",
        customer_phone="+14165550999",
        start_time=start,
        end_time=start + timedelta(hours=1),
        status=BookingStatus.CONFIRMED,
        source=BookingSource.MANUAL,
    )
    # No exception, no rows.
    assert OutboundMessage.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_re_save_does_not_double_enqueue(resource, customer):
    """Re-saving the same booking (no status change) is a no-op via idempotence."""
    booking = _future_booking(resource, customer, hours_ahead=48)
    before = OutboundMessage.objects.count()
    booking.save()
    booking.save()
    assert OutboundMessage.objects.count() == before


@pytest.mark.django_db(transaction=True)
def test_re_transition_to_no_show_is_idempotent(resource, customer):
    """Two saves with status=no_show only enqueue one row (reference idempotence)."""
    booking = _future_booking(resource, customer)
    booking.status = "no_show"
    booking.save()
    booking.save()
    assert OutboundMessage.objects.filter(template_key="no_show_followup").count() == 1


@pytest.mark.django_db(transaction=True)
def test_create_uses_customer_locale_pref(resource, store):
    zh_cust = Customer.objects.create(
        store=store, phone="+14165550222", name="小明", locale_pref="zh"
    )
    _future_booking(resource, zh_cust, hours_ahead=48)
    confirm = OutboundMessage.objects.get(template_key="booking_confirmation", customer=zh_cust)
    # zh template contains zh punctuation.
    assert "您" in confirm.body or "预订" in confirm.body


# ---------------------------------------------------------------------------
# STOP / UNSUBSCRIBE / 退订 handling on the inbound TwilioSmsAdapter
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_inbound_stop_adds_opt_out_tag(customer):
    TwilioSmsAdapter().normalize_inbound({"From": customer.phone, "Body": "STOP"})
    customer.refresh_from_db()
    assert "sms_opt_out" in customer.tags


@pytest.mark.django_db(transaction=True)
def test_inbound_unsubscribe_adds_opt_out_tag(customer):
    TwilioSmsAdapter().normalize_inbound({"From": customer.phone, "Body": "Unsubscribe"})
    customer.refresh_from_db()
    assert "sms_opt_out" in customer.tags


@pytest.mark.django_db(transaction=True)
def test_inbound_chinese_stop_adds_opt_out_tag(customer):
    TwilioSmsAdapter().normalize_inbound({"From": customer.phone, "Body": "退订"})
    customer.refresh_from_db()
    assert "sms_opt_out" in customer.tags


@pytest.mark.django_db(transaction=True)
def test_inbound_stop_with_whitespace_still_matches(customer):
    TwilioSmsAdapter().normalize_inbound({"From": customer.phone, "Body": "  stop  "})
    customer.refresh_from_db()
    assert "sms_opt_out" in customer.tags


@pytest.mark.django_db(transaction=True)
def test_inbound_stop_is_deduped(customer):
    """Two STOPs in a row leave one tag entry, not two."""
    TwilioSmsAdapter().normalize_inbound({"From": customer.phone, "Body": "STOP"})
    TwilioSmsAdapter().normalize_inbound({"From": customer.phone, "Body": "STOP"})
    customer.refresh_from_db()
    assert customer.tags.count("sms_opt_out") == 1


@pytest.mark.django_db(transaction=True)
def test_inbound_normal_message_does_not_opt_out(customer):
    TwilioSmsAdapter().normalize_inbound({"From": customer.phone, "Body": "what's available?"})
    customer.refresh_from_db()
    assert "sms_opt_out" not in (customer.tags or [])


@pytest.mark.django_db(transaction=True)
def test_inbound_stop_from_unknown_phone_is_noop(db):
    """STOP from a stranger does not create a Customer just to tag them."""
    TwilioSmsAdapter().normalize_inbound({"From": "+19998887777", "Body": "STOP"})
    assert Customer.objects.filter(phone="+19998887777").count() == 0


@pytest.mark.django_db(transaction=True)
def test_inbound_stop_preserves_existing_tags(customer):
    customer.tags = ["vip", "early-bird"]
    customer.save()
    TwilioSmsAdapter().normalize_inbound({"From": customer.phone, "Body": "STOP"})
    customer.refresh_from_db()
    assert set(customer.tags) == {"vip", "early-bird", "sms_opt_out"}
