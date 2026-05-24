"""Tests for the send_outbound management command + quiet hours."""

from __future__ import annotations

import threading
from datetime import datetime, time, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.db import connections
from django.utils import timezone

from agent.channels._test_helpers import LoggingOutboundAdapter
from agent.channels.outbound_base import OutboundChannelAdapter, OutboundSendResult
from agent.channels.registry import (
    register_outbound_adapter,
    unregister_outbound_adapter,
)
from core.models import Customer, Store
from outbound.models import OutboundChannel, OutboundMessage, OutboundStatus
from outbound.quiet_hours import next_send_time

# ---------------------------------------------------------------------------
# Adapters that override the "sms" channel for the duration of one test.
# ---------------------------------------------------------------------------


class _NotConfiguredAdapter(OutboundChannelAdapter):
    channel = "sms"

    def send(self, to_identifier, body, metadata=None):  # noqa: D401
        return OutboundSendResult(ok=False, reason="not_configured")


class _FailingAdapter(OutboundChannelAdapter):
    channel = "sms"

    def send(self, to_identifier, body, metadata=None):  # noqa: D401
        return OutboundSendResult(ok=False, reason="twilio_error: 21408")


class _CountingAdapter(OutboundChannelAdapter):
    """Records sends and reports the SID `count`."""

    channel = "sms"

    def __init__(self):
        self.calls = []

    def send(self, to_identifier, body, metadata=None):  # noqa: D401
        self.calls.append({"to": to_identifier, "body": body})
        return OutboundSendResult(ok=True, provider_message_id=f"SM_{len(self.calls)}")


@pytest.fixture(autouse=True)
def _restore_sms_registry():
    """Ensure each test starts with the default Twilio adapter registered."""
    yield
    unregister_outbound_adapter("sms")
    # Re-bootstrap by importing.
    from agent.channels.registry import _bootstrap

    _bootstrap()


@pytest.fixture()
def store(db):
    # Set quiet_hours_start == quiet_hours_end so quiet_hours.next_send_time
    # always treats this store as "never quiet". Without this, sender tests
    # run during 22:00-08:00 UTC (the model default window) get rescheduled
    # instead of sent — a real time-of-day flake.
    return Store.objects.create(
        name="Sender Store",
        timezone="UTC",
        business_hours={},
        quiet_hours_start=time(0, 0),
        quiet_hours_end=time(0, 0),
    )


@pytest.fixture()
def customer(store):
    return Customer.objects.create(
        store=store, phone="+14165550111", name="Alice", locale_pref="en"
    )


def _make_message(
    customer,
    *,
    template_key="reminder_24h",
    body="hello",
    scheduled_for=None,
    status=OutboundStatus.QUEUED,
    channel=OutboundChannel.SMS,
):
    return OutboundMessage.objects.create(
        customer=customer,
        channel=channel,
        template_key=template_key,
        body=body,
        scheduled_for=scheduled_for or timezone.now() - timedelta(seconds=1),
        status=status,
    )


def _run_sender():
    out = StringIO()
    call_command("send_outbound", stdout=out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Empty queue & basic dispatch
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_empty_queue_exits_cleanly(db):
    output = _run_sender()
    # No "processed" line because there was nothing to do.
    assert "[outbound]" not in output or "processed 0" in output


@pytest.mark.django_db(transaction=True)
def test_due_message_is_sent_when_adapter_succeeds(customer):
    counting = _CountingAdapter()
    register_outbound_adapter(counting)
    row = _make_message(customer)
    _run_sender()
    row.refresh_from_db()
    assert row.status == OutboundStatus.SENT
    assert row.sent_at is not None
    assert row.provider_message_id == "SM_1"
    assert counting.calls == [{"to": customer.phone, "body": "hello"}]


@pytest.mark.django_db(transaction=True)
def test_future_messages_are_skipped(customer):
    counting = _CountingAdapter()
    register_outbound_adapter(counting)
    _make_message(
        customer,
        scheduled_for=timezone.now() + timedelta(hours=1),
    )
    _run_sender()
    assert counting.calls == []


@pytest.mark.django_db(transaction=True)
def test_only_queued_rows_processed(customer):
    counting = _CountingAdapter()
    register_outbound_adapter(counting)
    _make_message(customer, status=OutboundStatus.SENT)
    _make_message(customer, status=OutboundStatus.CANCELLED)
    _make_message(customer, status=OutboundStatus.FAILED)
    due = _make_message(customer, status=OutboundStatus.QUEUED)
    _run_sender()
    due.refresh_from_db()
    assert due.status == OutboundStatus.SENT
    assert len(counting.calls) == 1


# ---------------------------------------------------------------------------
# Opt-out
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_opted_out_customer_is_cancelled(customer):
    counting = _CountingAdapter()
    register_outbound_adapter(counting)
    customer.tags = ["sms_opt_out"]
    customer.save()
    row = _make_message(customer)
    _run_sender()
    row.refresh_from_db()
    assert row.status == OutboundStatus.CANCELLED
    assert row.failure_reason == "opt_out"
    assert counting.calls == []  # adapter never called


# ---------------------------------------------------------------------------
# not_configured  →  stays queued, never failed
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_not_configured_keeps_row_queued(customer):
    register_outbound_adapter(_NotConfiguredAdapter())
    row = _make_message(customer)
    output = _run_sender()
    row.refresh_from_db()
    assert row.status == OutboundStatus.QUEUED
    assert "twilio not configured" in output


@pytest.mark.django_db(transaction=True)
def test_not_configured_logged_only_once_per_run(customer):
    register_outbound_adapter(_NotConfiguredAdapter())
    for _ in range(3):
        _make_message(customer)
    output = _run_sender()
    assert output.count("twilio not configured") == 1


# ---------------------------------------------------------------------------
# Generic adapter failure  →  marks row failed
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_generic_failure_marks_failed(customer):
    register_outbound_adapter(_FailingAdapter())
    row = _make_message(customer)
    _run_sender()
    row.refresh_from_db()
    assert row.status == OutboundStatus.FAILED
    assert "21408" in row.failure_reason


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------


def test_quiet_hours_outside_window_returns_unchanged(db):
    store = Store.objects.create(name="Q1", timezone="UTC", business_hours={})
    # Default 22:00 → 08:00 window; 14:00 UTC is outside.
    scheduled = datetime(2026, 5, 1, 14, 0, tzinfo=ZoneInfo("UTC"))
    assert next_send_time(scheduled, store) == scheduled


def test_quiet_hours_inside_window_advances_to_end(db):
    store = Store.objects.create(name="Q2", timezone="UTC", business_hours={})
    # 23:00 UTC is inside default quiet hours (22:00 → 08:00).
    scheduled = datetime(2026, 5, 1, 23, 0, tzinfo=ZoneInfo("UTC"))
    result = next_send_time(scheduled, store)
    # Should jump to the next 08:00 UTC.
    assert result == datetime(2026, 5, 2, 8, 0, tzinfo=ZoneInfo("UTC"))


def test_quiet_hours_urgent_bypass(db):
    store = Store.objects.create(name="Q3", timezone="UTC", business_hours={})
    scheduled = datetime(2026, 5, 1, 23, 0, tzinfo=ZoneInfo("UTC"))
    assert next_send_time(scheduled, store, urgent=True) == scheduled


def test_quiet_hours_same_day_window(db):
    store = Store.objects.create(
        name="Q4",
        timezone="UTC",
        business_hours={},
        quiet_hours_start=time(2, 0),
        quiet_hours_end=time(5, 0),
    )
    # Inside: 03:00 → next 05:00 same day.
    scheduled = datetime(2026, 5, 1, 3, 0, tzinfo=ZoneInfo("UTC"))
    result = next_send_time(scheduled, store)
    assert result == datetime(2026, 5, 1, 5, 0, tzinfo=ZoneInfo("UTC"))


def test_quiet_hours_degenerate_window_is_noop(db):
    """start == end means "no quiet hours" — send is always allowed."""
    store = Store.objects.create(
        name="Q5",
        timezone="UTC",
        business_hours={},
        quiet_hours_start=time(0, 0),
        quiet_hours_end=time(0, 0),
    )
    scheduled = datetime(2026, 5, 1, 3, 0, tzinfo=ZoneInfo("UTC"))
    assert next_send_time(scheduled, store) == scheduled


@pytest.mark.django_db(transaction=True)
def test_sender_reschedules_message_inside_quiet_hours(customer):
    counting = _CountingAdapter()
    register_outbound_adapter(counting)
    # Schedule the row for "now" but make the store's quiet window cover now.
    now = timezone.now()
    store = customer.store
    store.quiet_hours_start = (now - timedelta(hours=1)).time()
    store.quiet_hours_end = (now + timedelta(hours=2)).time()
    store.save()
    row = _make_message(customer, scheduled_for=now)
    _run_sender()
    row.refresh_from_db()
    # Still queued, scheduled_for advanced.
    assert row.status == OutboundStatus.QUEUED
    assert row.scheduled_for > now
    assert counting.calls == []


@pytest.mark.django_db(transaction=True)
def test_sender_sends_urgent_inside_quiet_hours(customer):
    """booking_confirmation bypasses quiet hours."""
    counting = _CountingAdapter()
    register_outbound_adapter(counting)
    now = timezone.now()
    store = customer.store
    store.quiet_hours_start = (now - timedelta(hours=1)).time()
    store.quiet_hours_end = (now + timedelta(hours=2)).time()
    store.save()
    row = _make_message(
        customer,
        template_key="booking_confirmation",
        scheduled_for=now,
    )
    _run_sender()
    row.refresh_from_db()
    assert row.status == OutboundStatus.SENT
    assert len(counting.calls) == 1


# ---------------------------------------------------------------------------
# Concurrency: two threads on the same queue process each row once
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_invocation_each_row_processed_once(customer):
    """Two workers, ten due rows → exactly ten sends, no duplicates."""
    LoggingOutboundAdapter.reset()
    log_adapter = LoggingOutboundAdapter()
    # Shadow the sms channel with the logger so both threads share state.
    register_outbound_adapter(type("_ShadowSms", (LoggingOutboundAdapter,), {"channel": "sms"})())

    for _ in range(10):
        _make_message(customer)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _worker():
        try:
            barrier.wait(timeout=5)
            call_command("send_outbound", stdout=StringIO())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connections.close_all()

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not errors, errors
    # Exactly 10 rows sent — no double-dispatch, no row stranded.
    sent = OutboundMessage.objects.filter(customer=customer, status=OutboundStatus.SENT).count()
    assert sent == 10
    # Reset for downstream tests.
    LoggingOutboundAdapter.reset()
    _ = log_adapter  # silence lint
