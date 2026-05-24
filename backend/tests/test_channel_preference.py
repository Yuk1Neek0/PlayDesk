"""Tests for `pick_channel_for()` + its integration into `enqueue_message`.

Verifies the implicit channel-preference rule:
- Customer with most-recent SMS conversation → defaults to SMS.
- Customer with most-recent WhatsApp conversation → defaults to WhatsApp.
- Customer with no inbound history → defaults to SMS.
- Customer with most-recent web_chat conversation → defaults to SMS
  (web_chat / phone / manual_staff aren't routable outbound).
- Explicit `enqueue_message(..., channel='whatsapp')` ignores the
  lookup.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Conversation, Customer, Store
from outbound.api import enqueue_message
from outbound.channel_pref import pick_channel_for


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Channel Pref Store", timezone="UTC", business_hours={})


@pytest.fixture()
def alice(store):
    return Customer.objects.create(store=store, phone="+14165550111", name="Alice")


def _ctx() -> dict:
    return {
        "customer_name": "x",
        "store_name": "Channel Pref Store",
        "start_time": "2026-10-01 18:00",
        "resource_name": "PS5 #1",
    }


def _make_conv(customer: Customer, channel: str, started_at=None) -> Conversation:
    """Create a Conversation, optionally backdating `started_at`."""
    conv = Conversation.objects.create(
        customer_identifier=customer.phone,
        channel=channel,
    )
    if started_at is not None:
        Conversation.objects.filter(pk=conv.pk).update(started_at=started_at)
    return conv


# ---------------------------------------------------------------------------
# pick_channel_for — unit-level
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_pick_channel_no_history_defaults_to_sms(alice):
    assert pick_channel_for(alice) == "sms"


@pytest.mark.django_db(transaction=True)
def test_pick_channel_most_recent_sms_returns_sms(alice):
    _make_conv(alice, "sms")
    assert pick_channel_for(alice) == "sms"


@pytest.mark.django_db(transaction=True)
def test_pick_channel_most_recent_whatsapp_returns_whatsapp(alice):
    _make_conv(alice, "whatsapp")
    assert pick_channel_for(alice) == "whatsapp"


@pytest.mark.django_db(transaction=True)
def test_pick_channel_most_recent_web_chat_defaults_to_sms(alice):
    """web_chat / phone / manual_staff are NOT outbound channels."""
    _make_conv(alice, "web_chat")
    assert pick_channel_for(alice) == "sms"


@pytest.mark.django_db(transaction=True)
def test_pick_channel_most_recent_phone_defaults_to_sms(alice):
    _make_conv(alice, "phone")
    assert pick_channel_for(alice) == "sms"


@pytest.mark.django_db(transaction=True)
def test_pick_channel_picks_newest_of_multiple(alice):
    """Older SMS, newer WhatsApp → WhatsApp wins."""
    now = timezone.now()
    _make_conv(alice, "sms", started_at=now - timedelta(days=2))
    _make_conv(alice, "whatsapp", started_at=now - timedelta(hours=1))
    assert pick_channel_for(alice) == "whatsapp"


@pytest.mark.django_db(transaction=True)
def test_pick_channel_ignores_web_chat_when_a_sms_exists(alice):
    """A more-recent web_chat does NOT mask an older SMS — we want
    the most recent *routable* channel."""
    now = timezone.now()
    _make_conv(alice, "sms", started_at=now - timedelta(days=1))
    _make_conv(alice, "web_chat", started_at=now)
    # web_chat isn't in the filter, so the older SMS wins.
    assert pick_channel_for(alice) == "sms"


@pytest.mark.django_db(transaction=True)
def test_pick_channel_other_customers_history_ignored(alice, store):
    """A different customer's WhatsApp conversation must not leak in."""
    bob = Customer.objects.create(store=store, phone="+14165550222", name="Bob")
    _make_conv(bob, "whatsapp")
    assert pick_channel_for(alice) == "sms"


@pytest.mark.django_db(transaction=True)
def test_pick_channel_customer_without_phone_defaults_to_sms(store):
    """A customer with an empty phone (rare but allowed) can't match
    any inbound conversation — fall back to SMS."""
    nameless = Customer.objects.create(store=store, phone="", name="Anon")
    assert pick_channel_for(nameless) == "sms"


# ---------------------------------------------------------------------------
# enqueue_message integration
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_enqueue_default_channel_uses_pick_for_whatsapp_customer(alice):
    _make_conv(alice, "whatsapp")
    row = enqueue_message(alice, "booking_confirmation", _ctx())
    assert row.channel == "whatsapp"


@pytest.mark.django_db(transaction=True)
def test_enqueue_default_channel_is_sms_for_sms_history(alice):
    _make_conv(alice, "sms")
    row = enqueue_message(alice, "booking_confirmation", _ctx())
    assert row.channel == "sms"


@pytest.mark.django_db(transaction=True)
def test_enqueue_default_channel_is_sms_for_no_history(alice):
    row = enqueue_message(alice, "booking_confirmation", _ctx())
    assert row.channel == "sms"


@pytest.mark.django_db(transaction=True)
def test_enqueue_explicit_channel_overrides_lookup(alice):
    """`channel='sms'` wins even when the customer last used WhatsApp."""
    _make_conv(alice, "whatsapp")
    row = enqueue_message(alice, "booking_confirmation", _ctx(), channel="sms")
    assert row.channel == "sms"


@pytest.mark.django_db(transaction=True)
def test_enqueue_explicit_whatsapp_overrides_lookup(alice):
    """`channel='whatsapp'` wins even with no inbound history."""
    row = enqueue_message(alice, "booking_confirmation", _ctx(), channel="whatsapp")
    assert row.channel == "whatsapp"
