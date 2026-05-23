---
name: outbound
status: completed
created: 2026-05-23T14:19:04Z
updated: 2026-05-23T16:43:38Z
progress: 100%
prd: .claude/prds/outbound.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/112
---

# Epic: outbound

## Overview

Add the outbound counterpart to the v3 multi-channel slice. One `OutboundMessage` queue, one `send_outbound` management command that drains it, an `OutboundChannelAdapter` ABC mirroring the existing inbound `ChannelAdapter`, a `TwilioSmsOutboundAdapter` wrapping the Twilio SDK, a small template registry rendered against `customer.locale_pref`, and booking signals that wire confirmation / 24h reminder / no-show / thank-you / cancellation. Quiet hours and a binary `sms_opt_out` tag (set by the existing inbound adapter when a customer replies STOP) are first-class so the pipeline is safe to enable in CI without real Twilio credentials.

## Architecture Decisions

- **Symmetric to inbound, not coupled.** The new `OutboundChannelAdapter` ABC lives alongside the existing inbound `ChannelAdapter` (`backend/agent/channels/base.py`) and shares the `channel` class-var so registry lookups work both directions — but the two ABCs do not share an interface (their shapes are different). Mirrors the v3 design rather than overloading it.
- **Queue first, sender second.** Booking signals always enqueue `OutboundMessage` rows; only the cron-driven `send_outbound` command talks to Twilio. This gives tests one assertion target (queue rows) and lets the wire degrade gracefully when creds are absent.
- **`not_configured` is not a failure.** When `TWILIO_AUTH_TOKEN` is unset, the adapter returns `{ ok: False, reason: "not_configured" }` and the sender leaves the row in `queued`. Tests assert on the queue, never the wire. The CI suite passes without secrets.
- **One template per locale, two locales.** `(en_template, zh_template)` tuples keyed by `template_key`. No per-store template customization in v4 — explicitly out of scope.
- **Cancellation cascades from booking lifecycle.** Cancelling a booking flips all matching `queued` rows to `cancelled` rather than relying on the sender to filter by `Booking.status` at send time (which would be a race).
- **Quiet hours respected at send time, not enqueue time.** An enqueued message scheduled inside quiet hours gets rescheduled to the next allowed boundary; only `booking_confirmation` is allowed to bypass.

## Technical Approach

### Frontend Components
- `frontend/src/app/admin/customers/[id]/page.tsx` — extend with a new "Outbound messages" card listing the last 20 rows for the customer (status pill, timestamp, body preview, failure reason on hover).
- No new pages — the entire outbound surface is one section on the existing customer detail page in v4.

### Backend Services
- `backend/outbound/__init__.py` — new Django app.
- `backend/outbound/models.py` — `OutboundMessage`; adds `Store.quiet_hours_start` / `Store.quiet_hours_end` via the migration.
- `backend/outbound/migrations/0001_initial.py` — `OutboundMessage` + two `Store` fields.
- `backend/agent/channels/outbound_base.py` — `OutboundChannelAdapter` ABC + `OutboundSendResult` dataclass (pure Python, no Django).
- `backend/agent/channels/twilio_sms_outbound.py` — `TwilioSmsOutboundAdapter`. Returns `not_configured` cleanly when creds absent.
- `backend/outbound/templates.py` — template registry `{ template_key: (en, zh) }` + `SafeFormatter` renderer.
- `backend/outbound/api.py` — public Python API: `enqueue_message(customer, template_key, context, scheduled_for=None, channel='sms', reference='')`. This is the entry point the `campaigns` slice imports.
- `backend/outbound/signals.py` — `Booking` `post_save` signal handling all four enqueue triggers + the `cancelled` cascade.
- `backend/outbound/management/commands/send_outbound.py` — the cron-driven sender. Selects with `SELECT ... FOR UPDATE SKIP LOCKED` for concurrency safety.
- `backend/outbound/quiet_hours.py` — `next_send_time(scheduled, store, urgent=False)` helper.
- `backend/agent/channels/twilio_sms.py` — extend the *existing inbound* adapter to detect STOP / UNSUBSCRIBE / 退订 in the message body and add `"sms_opt_out"` to `customer.tags`.
- `backend/api/views_outbound.py` — `GET /api/admin/outbound/?customer_id=N` + `?status=failed` admin endpoints.
- `docs/outbound-cron.md` — operator-facing doc on how to wire the command (every 60s, systemd timer or Docker sidecar).

### Infrastructure
- No new pip deps — the Twilio SDK is already vendored from the v3 multi-channel slice.
- No new env vars — reuses `TWILIO_AUTH_TOKEN` / `TWILIO_ACCOUNT_SID` / `TWILIO_FROM_NUMBER`.
- Operator must wire `python manage.py send_outbound` on a cron / timer (documented).

## Implementation Strategy

Model + ABC first, then the outbound adapter + sender command + templates, then the signals + opt-out + quiet hours, then the admin surface. Adapter + sender are deliberately decoupled so adding WhatsApp later is one new file + one registry entry.

## Task Breakdown Preview

- 001 — Migration: `OutboundMessage` model + `Store.quiet_hours_start/end` fields
- 002 — `OutboundChannelAdapter` ABC + `TwilioSmsOutboundAdapter` + adapter registry
- 003 — Template registry + `SafeFormatter` + `enqueue_message` public API
- 004 — Booking signals (confirmation + 24h reminder + no-show + thank-you + cancellation cascade) + STOP-handling on inbound adapter
- 005 — `send_outbound` management command + quiet hours + opt-out enforcement + `docs/outbound-cron.md`
- 006 — Admin endpoints + customer-detail "Outbound messages" section

## Dependencies

- Hard: `retention` (in main) — `Customer`, `customer.locale_pref`, `customer.tags`, `core.phone.normalize_phone`.
- Hard: `multi-channel` (in main) — reuses Twilio env vars, the existing inbound adapter (for STOP handling), the `ChannelAdapter` design pattern.
- Soft: `campaigns` (parallel v4 slice) — campaigns calls `enqueue_message`; if campaigns lands first it ships a stub and adopts the real API when this slice merges.
- Soft: `memberships` (parallel v4 slice) — tier-crossing notifications would route through outbound, but not in scope here.

## Success Criteria (Technical)

- Migration applies clean forward + reverse.
- Booking-create writes exactly two `OutboundMessage` rows (confirmation + 24h reminder).
- Marking `no_show` writes one row; marking `completed` writes one row; marking `cancelled` flips matching `queued` rows to `cancelled`.
- `send_outbound` processes only due `queued` rows, in oldest-first order, capped at 200 per run.
- With real Twilio creds in staging, an SMS arrives within one cron tick (~60s) of booking creation.
- Without Twilio creds, no row ever transitions to `failed` — they stay `queued` and the test suite passes.
- Opt-out tag check skips and marks `cancelled` (not `failed`).
- Existing backend test suite passes; ≥10 new tests cover signal triggers, the sender, quiet-hour rescheduling, opt-out cascade, and the `not_configured` skip path.

## Estimated Effort

- ~3 days for one developer.
- Critical path: 001 (schema) → 002 (adapter) → 003 (templates) → 004 (signals). Then 005 + 006 in parallel.

## Tasks Created
- [ ] #113 - Migration: OutboundMessage + Store.quiet_hours_start/end (parallel: false)
- [ ] #114 - OutboundChannelAdapter ABC + TwilioSmsOutboundAdapter + registry (parallel: true)
- [ ] #115 - Template registry + SafeFormatter + enqueue_message public API (parallel: true, depends on 001)
- [ ] #116 - Booking signals + STOP-handling on inbound adapter (parallel: false, depends on 003)
- [ ] #117 - send_outbound management command + quiet hours + opt-out + cron doc (parallel: true, depends on 002, 003)
- [ ] #118 - Admin endpoints + customer-detail "Outbound messages" section (parallel: true, depends on 001)

Total tasks: 6
Parallel tasks: 4
Sequential tasks: 2
Estimated total effort: 22 hours
