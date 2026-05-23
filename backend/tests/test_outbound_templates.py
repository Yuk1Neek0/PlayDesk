"""Tests for outbound templates + enqueue_message."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from core.models import Customer, Store
from outbound.api import enqueue_message
from outbound.models import OutboundMessage, OutboundStatus
from outbound.templates import TEMPLATES, render_template


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Template Store", timezone="UTC", business_hours={})


@pytest.fixture()
def en_customer(store):
    return Customer.objects.create(
        store=store, phone="+14165550111", name="Alice", locale_pref="en"
    )


@pytest.fixture()
def zh_customer(store):
    return Customer.objects.create(store=store, phone="+14165550222", name="小明", locale_pref="zh")


def _ctx():
    return {
        "customer_name": "Alice",
        "store_name": "Template Store",
        "start_time": "2026-10-01 18:00",
        "resource_name": "PS5 #1",
    }


def test_all_initial_templates_present():
    """The four templates the PRD calls out exist with both locales."""
    for key in ("booking_confirmation", "reminder_24h", "no_show_followup", "booking_thank_you"):
        assert key in TEMPLATES
        en, zh = TEMPLATES[key]
        assert en.strip() and zh.strip()


def test_render_en_template():
    body = render_template("booking_confirmation", "en", _ctx())
    assert "Alice" in body
    assert "Template Store" in body
    assert "PS5 #1" in body


def test_render_zh_template():
    body = render_template("booking_confirmation", "zh", _ctx())
    assert "Alice" in body
    assert "Template Store" in body
    assert "PS5 #1" in body
    # Sanity: zh version contains zh-specific punctuation.
    assert "您" in body or "预订" in body


def test_render_falls_back_to_en_for_unknown_locale():
    en_body = render_template("booking_confirmation", "en", _ctx())
    fallback = render_template("booking_confirmation", "fr", _ctx())
    assert fallback == en_body


def test_render_missing_context_key_raises_keyerror():
    with pytest.raises(KeyError) as excinfo:
        render_template("booking_confirmation", "en", {"customer_name": "Alice"})
    # The error message must name the template AND the missing key.
    assert "booking_confirmation" in str(excinfo.value)


def test_render_unknown_template_key_raises_keyerror():
    with pytest.raises(KeyError):
        render_template("does_not_exist", "en", {})


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_creates_row(en_customer):
    row = enqueue_message(en_customer, "booking_confirmation", _ctx())
    assert row.pk is not None
    assert row.customer_id == en_customer.id
    assert row.status == OutboundStatus.QUEUED
    assert row.template_key == "booking_confirmation"
    assert "Alice" in row.body
    assert row.scheduled_for is not None


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_uses_customer_locale_pref(zh_customer):
    row = enqueue_message(zh_customer, "booking_confirmation", _ctx())
    assert "您" in row.body or "预订" in row.body


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_default_scheduled_for_is_now(en_customer):
    before = timezone.now()
    row = enqueue_message(en_customer, "booking_confirmation", _ctx())
    after = timezone.now()
    assert before <= row.scheduled_for <= after


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_with_explicit_scheduled_for(en_customer):
    when = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
    row = enqueue_message(en_customer, "reminder_24h", _ctx(), scheduled_for=when)
    assert row.scheduled_for == when


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_is_idempotent_with_reference(en_customer):
    """Same (reference, template_key) → returns existing row, no duplicate."""
    row1 = enqueue_message(
        en_customer,
        "booking_confirmation",
        _ctx(),
        reference="booking:42:confirm",
    )
    row2 = enqueue_message(
        en_customer,
        "booking_confirmation",
        _ctx(),
        reference="booking:42:confirm",
    )
    assert row1.id == row2.id
    assert OutboundMessage.objects.filter(reference="booking:42:confirm").count() == 1


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_idempotence_sees_sent_rows(en_customer):
    """An already-sent row also blocks a duplicate enqueue."""
    row1 = enqueue_message(
        en_customer, "booking_confirmation", _ctx(), reference="booking:43:confirm"
    )
    row1.status = OutboundStatus.SENT
    row1.sent_at = timezone.now()
    row1.save()
    row2 = enqueue_message(
        en_customer, "booking_confirmation", _ctx(), reference="booking:43:confirm"
    )
    assert row1.id == row2.id


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_idempotence_does_not_block_cancelled(en_customer):
    """A cancelled row must not block a new enqueue (operator-driven re-send)."""
    row1 = enqueue_message(
        en_customer, "booking_confirmation", _ctx(), reference="booking:44:confirm"
    )
    row1.status = OutboundStatus.CANCELLED
    row1.save()
    row2 = enqueue_message(
        en_customer, "booking_confirmation", _ctx(), reference="booking:44:confirm"
    )
    assert row1.id != row2.id


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_empty_reference_always_writes(en_customer):
    """No reference → no idempotence guard, every call writes."""
    row1 = enqueue_message(en_customer, "booking_confirmation", _ctx())
    row2 = enqueue_message(en_customer, "booking_confirmation", _ctx())
    assert row1.id != row2.id


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_campaign_body_passthrough(en_customer):
    """campaigns slice uses body= to ship pre-rendered text without a template."""
    custom_body = "Hand-crafted campaign message — winter sale!"
    row = enqueue_message(
        en_customer,
        "campaign",
        context={},
        body=custom_body,
        reference="campaign:winter-2026",
    )
    assert row.body == custom_body
    assert row.template_key == "campaign"


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_unknown_template_without_body_raises(en_customer):
    with pytest.raises(KeyError):
        enqueue_message(en_customer, "no_such_template", context={})


@pytest.mark.django_db(transaction=True)
def test_enqueue_message_future_schedule(en_customer):
    """scheduled_for can be in the future (e.g. 24h reminder)."""
    when = timezone.now() + timedelta(hours=24)
    row = enqueue_message(en_customer, "reminder_24h", _ctx(), scheduled_for=when)
    assert row.scheduled_for == when
    assert row.status == OutboundStatus.QUEUED
