"""Tests for the ?channel= filter on /api/admin/conversations/."""

from __future__ import annotations

import pytest

from core.models import Conversation, Store


@pytest.fixture(autouse=True)
def _seed_store(db):
    """Conversation requires a Store; seed one so the save-fallback resolves."""
    Store.objects.get_or_create(
        name="Default Store", defaults={"timezone": "UTC", "business_hours": {}}
    )


@pytest.mark.django_db(transaction=True)
def test_no_filter_returns_all(client):
    Conversation.objects.create(customer_identifier="web-1", channel="web_chat")
    Conversation.objects.create(customer_identifier="+14165550111", channel="sms")
    resp = client.get("/api/admin/conversations/")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


@pytest.mark.django_db(transaction=True)
def test_filter_by_sms_narrows_list(client):
    Conversation.objects.create(customer_identifier="web-1", channel="web_chat")
    Conversation.objects.create(customer_identifier="+14165550111", channel="sms")
    Conversation.objects.create(customer_identifier="+14165550222", channel="sms")
    resp = client.get("/api/admin/conversations/?channel=sms")
    body = resp.json()
    assert body["count"] == 2
    assert all(c["channel"] == "sms" for c in body["results"])


@pytest.mark.django_db(transaction=True)
def test_unknown_channel_returns_empty(client):
    Conversation.objects.create(customer_identifier="web-1", channel="web_chat")
    resp = client.get("/api/admin/conversations/?channel=carrier-pigeon")
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@pytest.mark.django_db(transaction=True)
def test_response_includes_channel_field(client):
    Conversation.objects.create(customer_identifier="web-1", channel="web_chat")
    resp = client.get("/api/admin/conversations/")
    row = resp.json()["results"][0]
    assert row["channel"] == "web_chat"
