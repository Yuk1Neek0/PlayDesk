"""Promote stale CHECKED_IN bookings to COMPLETED.

Closes the v10b checkin booking lifecycle: customers who walked in via
`/c/<token>/` (or were manually flipped by staff) sit in CHECKED_IN
until this sweeper runs. A booking whose `end_time` is more than
``--grace-minutes`` ago is flipped to COMPLETED, which triggers the
existing `booking_thank_you` SMS via the v4 outbound signal.

Idempotent + safe to re-run hourly. Crontab pattern::

    0 * * * * cd /app && python manage.py auto_complete_checked_in

Flags::

    --grace-minutes N    overrides the 30-min default
    --dry-run            log what would happen without writing
    --store SLUG         scope to a single store (handy for staging)
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Booking, BookingStatus, Store
from outbound.api import enqueue_message

logger = logging.getLogger(__name__)

DEFAULT_GRACE_MINUTES = 30


class Command(BaseCommand):
    help = (
        "Promote stale CHECKED_IN bookings to COMPLETED + enqueue the "
        "booking_thank_you SMS. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--grace-minutes",
            type=int,
            default=DEFAULT_GRACE_MINUTES,
            help=(
                "Minutes after end_time before a CHECKED_IN booking is "
                f"promoted. Default: {DEFAULT_GRACE_MINUTES}."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log eligible bookings without writing.",
        )
        parser.add_argument(
            "--store",
            type=str,
            default=None,
            help="Optional store slug — scope the sweep to one location.",
        )

    def handle(self, *args, **options) -> None:
        grace_minutes = int(options["grace_minutes"])
        dry_run: bool = bool(options["dry_run"])
        store_slug: str | None = options["store"]

        cutoff = timezone.now() - timedelta(minutes=grace_minutes)
        qs = Booking.objects.filter(
            status=BookingStatus.CHECKED_IN,
            end_time__lt=cutoff,
        ).select_related("resource", "resource__store", "customer")

        if store_slug:
            if not Store.objects.filter(slug=store_slug).exists():
                self.stdout.write(self.style.WARNING(f"No store matches slug={store_slug!r}."))
                return
            qs = qs.filter(resource__store__slug=store_slug)

        promoted = 0
        for booking in qs:
            if dry_run:
                self.stdout.write(
                    f"[dry-run] would promote booking #{booking.pk} "
                    f"(end_time={booking.end_time.isoformat()})"
                )
                promoted += 1
                continue

            try:
                with transaction.atomic():
                    # select_for_update so a parallel admin "undo
                    # check-in" doesn't race us into double-touching
                    # the row. Plain query (no select_related) — the
                    # nullable customer FK trips Postgres's "FOR UPDATE
                    # cannot be applied to the nullable side of an
                    # outer join" check otherwise. We re-read the
                    # status inside the lock to catch a state change
                    # since the outer query.
                    locked = Booking.objects.select_for_update().get(pk=booking.pk)
                    if locked.status != BookingStatus.CHECKED_IN:
                        continue
                    locked.status = BookingStatus.COMPLETED
                    locked.save(update_fields=["status"])

                # SMS is a best-effort notification — a queue outage
                # mustn't prevent the state transition. Log + carry on.
                # `booking` already has the select_related'd customer +
                # resource.store fetched from the outer queryset, so
                # we read those off it rather than re-querying.
                if booking.customer_id is not None:
                    try:
                        enqueue_message(
                            booking.customer,
                            "booking_thank_you",
                            {
                                "customer_name": booking.customer.name or "",
                                "store_name": booking.resource.store.name,
                                "start_time": booking.start_time.strftime("%Y-%m-%d %H:%M"),
                                "resource_name": booking.resource.name,
                            },
                            reference=f"booking:{booking.id}:thank_you",
                        )
                    except Exception:
                        logger.exception(
                            "auto_complete_checked_in: enqueue failed for booking %s",
                            booking.pk,
                        )
                promoted += 1
            except Booking.DoesNotExist:
                # Booking deleted between the outer query and the lock —
                # nothing to promote.
                continue

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(f"{prefix}Promoted {promoted} CHECKED_IN booking(s)."))
