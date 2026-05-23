---
name: outbound
description: Outbound messaging pipeline — booking confirmations, 24h reminders, no-show recovery, thank-you follow-ups — over the existing Twilio SMS adapter, with quiet hours and opt-out built in.
status: backlog
created: 2026-05-23T14:19:04Z
---

# PRD: outbound

## Executive Summary

PlayDesk's v3 multi-channel slice landed a `ChannelAdapter` abstraction and a working Twilio SMS adapter (`backend/agent/channels/twilio_sms.py`) — but only on the **inbound** side. A customer can text the store and get an AI reply, yet the store cannot text the customer first. That gap blocks every "reduce no-shows / improve retention" story COSReady's public site advertises ("automated reminders and follow-ups").

This epic adds a symmetric outbound pipeline: an `OutboundChannelAdapter` ABC mirroring the inbound one, a `TwilioSmsOutboundAdapter` that wraps the Twilio Python SDK's `messages.create`, an `OutboundMessage` queue with a `send_outbound` management command that processes due messages, a small template registry rendered from booking + customer context, and signal-wired triggers off the existing `Booking` model. Quiet hours and a binary `sms_opt_out` tag (set when a customer replies STOP) are first-class so the pipeline is safe to enable in CI without a real Twilio key.

## Problem Statement

The existing booking flow ends when the booking row is written. No confirmation goes out, no reminder ever fires, no recovery message lands after a no-show, no thank-you reaches the customer afterward. Every front-desk team has to do this manually today, which is exactly the workload COSReady's "AI front desk" promises to remove.

Building this as four separate cron jobs each calling Twilio directly would mean four divergent code paths and no way to ever swap SMS for WhatsApp or email. We need one queue, one sender, one template registry, and one place to add a new channel.

## User Stories

- **As a customer**, within 30 seconds of booking I receive an SMS confirming the date / time / resource, and the message respects my preferred language (`Customer.locale_pref`).
  - *Acceptance:* an `OutboundMessage` row is created with `status = "queued"` immediately on booking creation; the `send_outbound` command picks it up and Twilio's mock returns success in tests.
- **As a customer**, 24 hours before my appointment I get a reminder SMS, unless I've opted out.
  - *Acceptance:* the reminder is queued with `scheduled_for = booking.scheduled_at - 24h`; if `customer.tags` contains `"sms_opt_out"` the message is marked `cancelled` rather than sent.
- **As staff**, when I mark a booking as no-show, the customer receives a polite recovery message within a minute ("we missed you — want to rebook?").
  - *Acceptance:* the no-show signal enqueues a `no_show_followup` template; the `send_outbound` cron picks it up on its next tick.
- **As staff**, I can open a customer's detail page and see every outbound message we've sent them, with status, timestamp, body, and failure reason if any.
  - *Acceptance:* `/admin/customers/{id}` gains an "Outbound messages" section listing rows from `OutboundMessage`.
- **As a developer**, I can swap Twilio for a different SMS provider by writing one `OutboundChannelAdapter` subclass and registering it; no other code in the project changes.
  - *Acceptance:* a `LoggingOutboundAdapter` fake exists for tests; the `send_outbound` command picks adapters from a registry keyed by `channel`.
- **As a CI maintainer**, the test suite never fails because Twilio creds are absent — the pipeline silently degrades to no-op delivery and asserts on the queue rather than the wire.
  - *Acceptance:* when `TWILIO_AUTH_TOKEN` is unset, `send_outbound` logs `[outbound] skipped sms_send: twilio not configured` and moves on; messages stay `queued` (not failed).

## Functional Requirements

1. **`OutboundMessage` model**:
   - `customer (FK)`, `channel ('sms' | 'web_chat')`, `template_key (str)`, `body (rendered text)`, `status ('queued' | 'sent' | 'failed' | 'cancelled')`, `scheduled_for (datetime, default now)`, `sent_at (datetime, nullable)`, `failure_reason (str, nullable)`, `reference (str — e.g. "booking:42")`, `created_at`.
   - Indexed on `(status, scheduled_for)` so the sender query is one range scan.
2. **`OutboundChannelAdapter` ABC** in `backend/agent/channels/outbound_base.py`:
   - `channel: ClassVar[str]` — matches the inbound adapter's channel constant.
   - `send(to_identifier: str, body: str, metadata: dict | None = None) -> OutboundSendResult` — returns `{ ok: bool, provider_message_id: str | None, reason: str | None }`.
   - Pure Python, no Django imports — mirrors `backend/agent/channels/base.py`.
3. **`TwilioSmsOutboundAdapter`** in `backend/agent/channels/twilio_sms_outbound.py`:
   - Uses the same `TWILIO_AUTH_TOKEN` / `TWILIO_ACCOUNT_SID` / `TWILIO_FROM_NUMBER` env vars as the inbound adapter.
   - Returns `{ ok: False, reason: "not_configured" }` when creds are missing — never raises.
   - On success returns the Twilio message SID as `provider_message_id` for traceability.
4. **Template registry** in `backend/outbound/templates.py`:
   - A dict keyed by `template_key` mapping to `(en_template, zh_template)` pairs.
   - Templates render with `str.format_map(SafeFormatter(context))` so a missing key is a clear error, not a silent empty string.
   - Initial templates: `booking_confirmation`, `reminder_24h`, `no_show_followup`, `booking_thank_you`.
5. **`enqueue_message(customer, template_key, context, scheduled_for=None, channel='sms', reference='')`** helper:
   - Renders the template against `customer.locale_pref`.
   - Writes one `OutboundMessage` row.
   - Returns the row for caller-side traceability.
   - Idempotent if the caller passes a unique `reference` and an `OutboundMessage` with the same `(reference, template_key)` already exists in `queued`/`sent` status (avoids double-sending on signal re-fire).
6. **Booking signals** in `backend/outbound/signals.py`:
   - `post_save Booking` (new): enqueue `booking_confirmation` immediately + `reminder_24h` scheduled for `scheduled_at - 24h` (only if that's in the future).
   - `post_save Booking` (status → `no_show`): enqueue `no_show_followup` immediately.
   - `post_save Booking` (status → `completed`): enqueue `booking_thank_you` immediately.
   - `post_save Booking` (status → `cancelled`): mark all `OutboundMessage` rows with `reference = "booking:<id>"` and `status = "queued"` as `cancelled`.
7. **`python manage.py send_outbound` management command**:
   - Selects `OutboundMessage` rows with `status = "queued"` and `scheduled_for <= now()` (ordered oldest-first).
   - For each, looks up the adapter via the registry, calls `send()`, and updates the row in a single transaction.
   - On failure, sets `status = "failed"` and `failure_reason`.
   - Caps each run at 200 messages to bound runtime.
   - Documented for cron via `docs/outbound-cron.md` (suggest every 60 seconds).
8. **Quiet hours**:
   - `Store.quiet_hours_start` + `Store.quiet_hours_end` (default `22:00` / `08:00`, store-local).
   - At send time, if `now()` in store-local time is inside quiet hours, the message is rescheduled to the next allowed boundary; only "urgent" templates (currently `booking_confirmation`) bypass quiet hours.
9. **Opt-out**:
   - The existing inbound Twilio adapter detects a body of `STOP` / `UNSUBSCRIBE` / `退订` (case-insensitive) and adds `"sms_opt_out"` to `customer.tags`.
   - `send_outbound` skips and marks `cancelled` any message for an opted-out customer.
10. **Admin endpoints**:
    - `GET /api/admin/outbound/?customer_id=N` — message log for one customer, newest-first.
    - `GET /api/admin/outbound/?status=failed&limit=50` — failure inspection.
11. **Customer-detail frontend section** — `/admin/customers/[id]` gains an "Outbound messages" card listing the last 20 rows with status pill (queued / sent / failed / cancelled), timestamp, body preview, failure reason on hover.

## Non-Functional Requirements

- `send_outbound` is safe to run concurrently — message selection uses `SELECT ... FOR UPDATE SKIP LOCKED` so two workers never grab the same row.
- The pipeline produces no failed-test in CI without real Twilio credentials — `not_configured` returns leave messages `queued`, and tests assert on the queue, not the wire.
- Template rendering never silently swallows a missing context key — missing keys raise `KeyError` at enqueue time, not in production at send time.
- One additive migration (`OutboundMessage` + the two `Store` quiet-hours fields). No backfill.
- The opt-out path is irrevocable from the customer side — once `sms_opt_out` is on the tag list, only staff (via the existing tag-edit UI from retention) can remove it.

## Success Criteria

- Creating a booking writes exactly two `OutboundMessage` rows (`booking_confirmation` immediate + `reminder_24h` scheduled).
- Marking a booking `no_show` writes exactly one `no_show_followup` row.
- Marking a booking `cancelled` flips all matching `queued` rows to `cancelled`.
- `send_outbound` against a seeded queue with mixed states processes only due `queued` rows, respects quiet hours, and respects opt-out.
- With real Twilio creds in staging, a SMS arrives on a test phone within ~60s of booking creation (one cron tick).
- Without Twilio creds, the entire test suite passes and no rows ever transition to `failed`.

## Constraints & Assumptions

- SMS is the only outbound channel in v4. WhatsApp follows the same `OutboundChannelAdapter` contract in a future slice.
- Quiet hours are store-local, not customer-local — we don't know a customer's timezone in v4.
- One template per language (`en` / `zh`) — no per-store template customization yet.
- The cron interval is operator-configured (the command is idempotent and can run as fast as every 30s).
- Phone identity uses E.164 via the existing `core.phone.normalize_phone()` helper from retention.

## Out of Scope

- WhatsApp / RCS / email delivery channels.
- Per-store template customization (CMS-style editing).
- Two-way reply threading beyond the existing inbound adapter (an SMS reply to an outbound message still routes through the normal inbound webhook, no special pairing).
- Drip / multi-step campaigns (covered by the parallel `campaigns` slice).
- Customer-self-serve subscription preferences (only the binary `sms_opt_out` tag in v4).
- Delivery-status webhooks (Twilio status callbacks) — we trust the synchronous `messages.create` return for v4.

## Dependencies

- Hard: `retention` (already in main) — uses `Customer`, `customer.locale_pref`, `customer.tags`, and `core.phone.normalize_phone()`.
- Hard: `multi-channel` (already in main) — reuses `ChannelAdapter`'s shape and the existing Twilio env vars; the inbound adapter's `STOP`-handling lives on the inbound side of the same wire.
- Soft: `campaigns` (parallel v4 slice) — campaigns calls into `enqueue_message`, but if campaigns lands first it ships with a stub that logs+no-ops, and adopts the real `enqueue_message` once this slice merges. Mirrors the v3 retention↔multi-channel pattern.
