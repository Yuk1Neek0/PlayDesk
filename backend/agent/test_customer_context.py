"""Tests for v11b customer-context injection into the agent system prompt."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from agent.loop import _build_customer_context
from core.memberships import award_points
from core.models import (
    Conversation,
    ConversationChannel,
    Customer,
    RewardTier,
    Store,
)


@pytest.fixture()
def store(db):
    return Store.objects.create(
        name="CtxStore",
        slug="ctxstore",
        timezone="UTC",
        business_hours={},
    )


@pytest.fixture()
def customer(store):
    c = Customer.objects.create(
        store=store,
        phone="+15551231234",
        name="Alice Wong",
        total_visits=12,
        last_visit_at=timezone.now() - timedelta(days=4),
        tags=["vip", "sms_opt_out"],
    )
    return c


def _make_conversation(store, identifier, channel=ConversationChannel.SMS):
    return Conversation.objects.create(
        store=store,
        customer_identifier=identifier,
        channel=channel,
    )


def test_resolved_customer_yields_context_block(store, customer):
    conv = _make_conversation(store, customer.phone)
    block = _build_customer_context(conv)
    assert block is not None
    assert "## Customer Context" in block
    assert "Alice Wong" in block
    assert "Total visits: 12" in block
    # last_visit_at present
    assert "Last visit:" in block
    # surfaced tag present, private tag filtered
    assert "vip" in block
    assert "sms_opt_out" not in block


def test_unmatched_phone_returns_none(store):
    conv = _make_conversation(store, "+15559999999")
    assert _build_customer_context(conv) is None


def test_empty_identifier_returns_none(store):
    conv = _make_conversation(store, "", channel=ConversationChannel.WEB_CHAT)
    assert _build_customer_context(conv) is None


def test_tier_and_balance_surfaced_when_present(store, customer):
    # Award enough lifetime points to land in a tier.
    bronze = RewardTier.objects.create(
        store=store, name="Bronze", min_lifetime_points=10, position=1
    )
    award_points(customer, 50, "test", "seed")
    conv = _make_conversation(store, customer.phone)
    block = _build_customer_context(conv)
    assert "Loyalty tier: Bronze" in block
    assert "Points balance: 50" in block
    # Reference the fixture so it's not unused.
    assert bronze.pk is not None


def test_customer_with_no_name_skips_name_line(store):
    Customer.objects.create(store=store, phone="+15550001111", name="", total_visits=0)
    conv = _make_conversation(store, "+15550001111")
    block = _build_customer_context(conv)
    assert block is not None
    assert "Name:" not in block
    assert "Total visits: 0" in block
