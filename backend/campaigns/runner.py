"""
Synchronous send-pipeline for campaigns.

`send_campaign(campaign_id, sent_by)` runs in two phases:

  1. Inside one DB transaction: lock the campaign, snapshot recipients
     into `CampaignRun` rows (one per match, plus `skipped_optout` rows
     for opted-out customers), set `recipient_snapshot_count`, commit.
  2. Outside the transaction: iterate queued runs, render the body, call
     `send_campaign_message`, update each run's terminal status.

This shape keeps the send loop out of a long-running lock.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from .models import Campaign, CampaignRun, CampaignRunStatus, CampaignStatus
from .rendering import render
from .segments import customers_for
from .send import send_campaign_message

logger = logging.getLogger(__name__)

RECIPIENT_CAP = 1000


class CampaignAlreadyProcessed(Exception):
    """Campaign is past `draft`/`scheduled` — re-send / re-edit refused."""


class CampaignTooLarge(Exception):
    """Recipient count exceeds the v4 synchronous-send cap."""


def send_campaign(campaign_id: int, sent_by=None) -> dict:
    """Run the campaign and return a summary dict.

    Returns: {"sent": N, "failed": N, "skipped": N, "snapshot_count": N}
    """
    # Snapshot phase — locked, atomic, no I/O outside DB.
    with transaction.atomic():
        try:
            campaign = (
                Campaign.objects.select_for_update()
                .select_related("segment", "store")
                .get(pk=campaign_id)
            )
        except Campaign.DoesNotExist as exc:
            raise CampaignAlreadyProcessed("campaign_not_found") from exc

        if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED):
            raise CampaignAlreadyProcessed(campaign.status)

        recipients = list(customers_for(campaign.segment))
        if len(recipients) > RECIPIENT_CAP:
            raise CampaignTooLarge(f"{len(recipients)} > {RECIPIENT_CAP}")

        runs_to_create = []
        for customer in recipients:
            tags = customer.tags or []
            is_optout = "sms_opt_out" in tags
            runs_to_create.append(
                CampaignRun(
                    campaign=campaign,
                    customer=customer,
                    status=(
                        CampaignRunStatus.SKIPPED_OPTOUT if is_optout else CampaignRunStatus.QUEUED
                    ),
                )
            )
        CampaignRun.objects.bulk_create(runs_to_create)

        campaign.status = CampaignStatus.SENDING
        if sent_by is not None and getattr(sent_by, "is_authenticated", False):
            campaign.sent_by = sent_by
        campaign.recipient_snapshot_count = len(runs_to_create)
        campaign.save(update_fields=["status", "sent_by", "recipient_snapshot_count"])

    # Send phase — outside the transaction so we don't hold locks during I/O.
    sent_count = 0
    failed_count = 0
    skipped_count = CampaignRun.objects.filter(
        campaign_id=campaign_id, status=CampaignRunStatus.SKIPPED_OPTOUT
    ).count()

    queued = (
        CampaignRun.objects.filter(campaign_id=campaign_id, status=CampaignRunStatus.QUEUED)
        .select_related("customer")
        .order_by("id")
    )

    for run in queued:
        body = render(
            campaign.body_template,
            {"customer": run.customer, "store": campaign.store},
        )
        result = send_campaign_message(
            run.customer,
            body,
            reference=f"campaign:{campaign.pk}:run:{run.pk}",
        )
        if result.ok:
            run.status = CampaignRunStatus.SENT
            run.sent_at = timezone.now()
            if result.provider_message_id:
                run.outbound_message_id = result.provider_message_id
            run.save(update_fields=["status", "sent_at", "outbound_message_id"])
            sent_count += 1
        else:
            run.status = CampaignRunStatus.FAILED
            run.failure_reason = result.reason or "unknown"
            run.save(update_fields=["status", "failure_reason"])
            failed_count += 1

    campaign.status = CampaignStatus.SENT
    campaign.sent_at = timezone.now()
    campaign.save(update_fields=["status", "sent_at"])

    return {
        "sent": sent_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "snapshot_count": campaign.recipient_snapshot_count,
    }


def cancel_campaign(campaign_id: int) -> Campaign:
    """Flip a draft/scheduled campaign to `cancelled`. Raises
    `CampaignAlreadyProcessed` past that point."""
    with transaction.atomic():
        campaign = Campaign.objects.select_for_update().get(pk=campaign_id)
        if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED):
            raise CampaignAlreadyProcessed(campaign.status)
        campaign.status = CampaignStatus.CANCELLED
        campaign.save(update_fields=["status"])
    return campaign


__all__ = [
    "CampaignAlreadyProcessed",
    "CampaignTooLarge",
    "RECIPIENT_CAP",
    "cancel_campaign",
    "send_campaign",
]
