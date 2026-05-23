"""Tests for `send_campaign` runner + `cancel_campaign` + state machine
+ body rendering. Exercises both stub and real send impls in one run via
the `force_send_impl` fixture from task 003."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from campaigns.models import Campaign, CampaignRun, CampaignRunStatus, CampaignStatus, Segment
from campaigns.runner import (
    RECIPIENT_CAP,
    CampaignAlreadyProcessed,
    CampaignTooLarge,
    cancel_campaign,
    send_campaign,
)
from campaigns.send import SendResult, _stub_impl, force_send_impl
from core.models import Customer, Store


@pytest.fixture()
def store(db):
    return Store.objects.create(name="Runner Store", timezone="UTC", business_hours={})


@pytest.fixture()
def segment(store):
    return Segment.objects.create(store=store, name="Everyone", filter={})


def _make_campaign(store, segment, body="Hi {customer.name}, welcome to {store.name}"):
    return Campaign.objects.create(
        store=store,
        name="Drop",
        segment=segment,
        body_template=body,
    )


def _make_customers(store, n=5, optouts: tuple[int, ...] = ()):
    out = []
    for i in range(n):
        tags = ["sms_opt_out"] if i in optouts else []
        out.append(
            Customer.objects.create(
                store=store,
                phone=f"+1416555{i:04d}",
                name=f"Cust{i}",
                tags=tags,
                last_visit_at=timezone.now() - timedelta(days=1),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_happy_path_with_optouts(store, segment):
    _make_customers(store, n=5, optouts=(2,))
    campaign = _make_campaign(store, segment)

    with force_send_impl(_stub_impl):
        summary = send_campaign(campaign.pk)

    assert summary == {"sent": 4, "failed": 0, "skipped": 1, "snapshot_count": 5}

    campaign.refresh_from_db()
    assert campaign.status == CampaignStatus.SENT
    assert campaign.sent_at is not None
    assert campaign.recipient_snapshot_count == 5

    # No orphan queued runs.
    assert not CampaignRun.objects.filter(
        campaign=campaign, status=CampaignRunStatus.QUEUED
    ).exists()
    assert CampaignRun.objects.filter(campaign=campaign, status=CampaignRunStatus.SENT).count() == 4
    assert (
        CampaignRun.objects.filter(
            campaign=campaign, status=CampaignRunStatus.SKIPPED_OPTOUT
        ).count()
        == 1
    )


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_resend_protection(store, segment):
    _make_customers(store, n=2)
    campaign = _make_campaign(store, segment)
    with force_send_impl(_stub_impl):
        send_campaign(campaign.pk)
        with pytest.raises(CampaignAlreadyProcessed):
            send_campaign(campaign.pk)


@pytest.mark.django_db(transaction=True)
def test_cancel_draft_then_cannot_resend(store, segment):
    _make_customers(store, n=2)
    campaign = _make_campaign(store, segment)
    cancel_campaign(campaign.pk)
    campaign.refresh_from_db()
    assert campaign.status == CampaignStatus.CANCELLED
    with pytest.raises(CampaignAlreadyProcessed):
        send_campaign(campaign.pk)


@pytest.mark.django_db(transaction=True)
def test_cannot_cancel_after_sent(store, segment):
    _make_customers(store, n=1)
    campaign = _make_campaign(store, segment)
    with force_send_impl(_stub_impl):
        send_campaign(campaign.pk)
    with pytest.raises(CampaignAlreadyProcessed):
        cancel_campaign(campaign.pk)


# ---------------------------------------------------------------------------
# Recipient cap
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_recipient_cap_keeps_campaign_in_draft(store, segment, monkeypatch):
    # Override the cap to keep the test fast.
    monkeypatch.setattr("campaigns.runner.RECIPIENT_CAP", 3)
    _make_customers(store, n=5)
    campaign = _make_campaign(store, segment)
    with force_send_impl(_stub_impl), pytest.raises(CampaignTooLarge):
        send_campaign(campaign.pk)
    campaign.refresh_from_db()
    assert campaign.status == CampaignStatus.DRAFT
    assert campaign.recipient_snapshot_count == 0
    assert not CampaignRun.objects.filter(campaign=campaign).exists()


@pytest.mark.django_db
def test_recipient_cap_constant_is_one_thousand():
    assert RECIPIENT_CAP == 1000


# ---------------------------------------------------------------------------
# Body rendering
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_missing_template_key_raises(store, segment):
    _make_customers(store, n=1)
    campaign = _make_campaign(store, segment, body="Hi {customer.does_not_exist}")
    with force_send_impl(_stub_impl), pytest.raises(KeyError):
        send_campaign(campaign.pk)


# ---------------------------------------------------------------------------
# Both impls covered in one test run
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_both_send_impls_in_one_run(store, segment):
    """Same test process exercises stub then a fake real impl by swapping
    the bound implementation via force_send_impl."""
    _make_customers(store, n=2)
    c1 = _make_campaign(store, segment)
    c2 = _make_campaign(store, segment)

    calls: list[str] = []

    def fake_real(customer, body, reference):
        calls.append(reference)
        return SendResult(ok=True, provider_message_id="X-1", reason=None)

    with force_send_impl(_stub_impl):
        s1 = send_campaign(c1.pk)
    with force_send_impl(fake_real):
        s2 = send_campaign(c2.pk)

    assert s1["sent"] == 2
    assert s2["sent"] == 2
    # Real path populated outbound_message_id; stub path left it blank.
    real_runs = CampaignRun.objects.filter(campaign=c2)
    assert all(r.outbound_message_id == "X-1" for r in real_runs)
    stub_runs = CampaignRun.objects.filter(campaign=c1)
    assert all(r.outbound_message_id == "" for r in stub_runs)
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Snapshot atomicity — customer added after send is not included
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_snapshot_excludes_late_added_customer(store, segment):
    _make_customers(store, n=2)
    campaign = _make_campaign(store, segment)
    with force_send_impl(_stub_impl):
        summary = send_campaign(campaign.pk)
    assert summary["snapshot_count"] == 2

    # Add a third customer after send — should not be retroactively included.
    Customer.objects.create(store=store, phone="+12223334444", name="Late")
    campaign.refresh_from_db()
    assert campaign.recipient_snapshot_count == 2
    assert CampaignRun.objects.filter(campaign=campaign).count() == 2


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_failed_send_records_reason(store, segment):
    _make_customers(store, n=2)
    campaign = _make_campaign(store, segment)

    def failing_impl(customer, body, reference):
        return SendResult(ok=False, provider_message_id=None, reason="provider_down")

    with force_send_impl(failing_impl):
        summary = send_campaign(campaign.pk)

    assert summary["sent"] == 0
    assert summary["failed"] == 2
    failed = CampaignRun.objects.filter(campaign=campaign, status=CampaignRunStatus.FAILED)
    assert failed.count() == 2
    assert all(r.failure_reason == "provider_down" for r in failed)
