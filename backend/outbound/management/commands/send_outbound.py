"""Drain the OutboundMessage queue.

Selects due `queued` rows (oldest-first, capped at 200), picks the
registered adapter by `channel`, and dispatches each row inside its own
small transaction. Concurrency-safe via `SELECT … FOR UPDATE SKIP LOCKED`
so two cron invocations never grab the same row.

Per-row decision tree:
  - customer.tags ∋ "sms_opt_out"  → cancel, reason="opt_out"
  - quiet hours apply (non-urgent) → reschedule, leave queued
  - adapter.send() returns ok=True → mark sent, store provider_message_id
  - adapter.send() returns reason="not_configured" → leave queued,
    log once per run (CI-without-secrets path)
  - any other adapter failure     → mark failed, store failure_reason

Wire as a cron / systemd timer at ~60s cadence (see docs/outbound-cron.md).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from agent.channels.registry import get_outbound_adapter

from ...models import OutboundMessage, OutboundStatus
from ...quiet_hours import next_send_time
from ...templates import URGENT_TEMPLATE_KEYS

# Cap each run so a backlog spike can't tie up the worker forever.
BATCH_SIZE = 200


class Command(BaseCommand):
    help = "Drain the OutboundMessage queue (process due queued rows once)."

    def add_arguments(self, parser) -> None:  # noqa: D401
        parser.add_argument(
            "--limit",
            type=int,
            default=BATCH_SIZE,
            help=f"Maximum rows to process this run (default: {BATCH_SIZE}).",
        )

    def handle(self, *args, **options) -> None:
        limit = max(1, int(options.get("limit") or BATCH_SIZE))
        now = timezone.now()

        # Pick row IDs upfront so each row's transaction is short.
        due_ids = list(
            OutboundMessage.objects.filter(
                status=OutboundStatus.QUEUED,
                scheduled_for__lte=now,
            )
            .order_by("scheduled_for")
            .values_list("id", flat=True)[:limit]
        )

        if not due_ids:
            return

        not_configured_logged = False
        processed = 0

        for row_id in due_ids:
            with transaction.atomic():
                # Lock ONLY the OutboundMessage row, not the joined
                # customer/store. With `skip_locked=True`, locking joined
                # tables would also skip when another worker holds the
                # customer's row — surprising failure mode when multiple
                # messages belong to the same customer.
                row = (
                    OutboundMessage.objects.select_for_update(
                        skip_locked=True,
                        of=("self",),
                    )
                    .select_related("customer", "customer__store")
                    .filter(id=row_id, status=OutboundStatus.QUEUED)
                    .first()
                )
                if row is None:
                    continue  # Already picked up by a sibling worker.

                customer = row.customer

                # 1) Opt-out cascade.
                if "sms_opt_out" in (customer.tags or []):
                    row.status = OutboundStatus.CANCELLED
                    row.failure_reason = "opt_out"
                    row.save(update_fields=["status", "failure_reason"])
                    processed += 1
                    continue

                # 2) Quiet hours (urgent templates bypass).
                urgent = row.template_key in URGENT_TEMPLATE_KEYS
                store = customer.store
                allowed_at = next_send_time(row.scheduled_for, store, urgent=urgent)
                if allowed_at > row.scheduled_for:
                    row.scheduled_for = allowed_at
                    row.save(update_fields=["scheduled_for"])
                    processed += 1
                    continue

                # 3) Dispatch.
                try:
                    adapter = get_outbound_adapter(row.channel)
                except KeyError:
                    row.status = OutboundStatus.FAILED
                    row.failure_reason = f"no adapter for channel {row.channel!r}"
                    row.save(update_fields=["status", "failure_reason"])
                    processed += 1
                    continue

                result = adapter.send(customer.phone, row.body)
                if result.ok:
                    row.status = OutboundStatus.SENT
                    row.sent_at = timezone.now()
                    if result.provider_message_id:
                        row.provider_message_id = result.provider_message_id
                    row.save(update_fields=["status", "sent_at", "provider_message_id"])
                elif result.reason == "not_configured":
                    # Keep the row queued — operator hasn't wired Twilio yet.
                    if not not_configured_logged:
                        self.stdout.write("[outbound] skipped: twilio not configured")
                        not_configured_logged = True
                else:
                    row.status = OutboundStatus.FAILED
                    row.failure_reason = result.reason or "unknown"
                    row.save(update_fields=["status", "failure_reason"])
                processed += 1

        self.stdout.write(f"[outbound] processed {processed} row(s)")
