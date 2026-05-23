"""Schema-level tests for the campaigns app — creation, defaults, and the
unique (campaign, customer) constraint."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from campaigns.models import (
    Campaign,
    CampaignRun,
    CampaignRunStatus,
    CampaignStatus,
    Segment,
)
from core.models import Customer, Store


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Schema Store", timezone="UTC", business_hours={})


@pytest.fixture()
def customer(store):
    return Customer.objects.create(store=store, phone="+14165550000", name="Alice")


@pytest.fixture()
def segment(store):
    return Segment.objects.create(store=store, name="VIPs", filter={"tags_include": ["vip"]})


@pytest.fixture()
def campaign(store, segment):
    return Campaign.objects.create(
        store=store,
        name="May Drop",
        segment=segment,
        body_template="Hi {customer.name}",
    )


@pytest.mark.django_db
def test_segment_defaults(store):
    seg = Segment.objects.create(store=store, name="Empty")
    assert seg.filter == {}
    assert seg.created_at is not None


@pytest.mark.django_db
def test_campaign_defaults(campaign):
    assert campaign.status == CampaignStatus.DRAFT
    assert campaign.recipient_snapshot_count == 0
    assert campaign.scheduled_for is not None
    assert campaign.sent_at is None
    assert campaign.sent_by is None


@pytest.mark.django_db
def test_campaign_run_unique_per_customer(campaign, customer):
    CampaignRun.objects.create(campaign=campaign, customer=customer)
    with pytest.raises(IntegrityError), transaction.atomic():
        CampaignRun.objects.create(campaign=campaign, customer=customer)


@pytest.mark.django_db
def test_campaign_run_status_default(campaign, customer):
    run = CampaignRun.objects.create(campaign=campaign, customer=customer)
    assert run.status == CampaignRunStatus.QUEUED
    assert run.outbound_message_id == ""
    assert run.failure_reason == ""
    assert run.sent_at is None


@pytest.mark.django_db
def test_segment_protected_when_campaign_references_it(campaign, segment):
    with pytest.raises(ProtectedError):
        segment.delete()
