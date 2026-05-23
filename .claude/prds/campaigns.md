---
name: campaigns
description: Customer segmentation + one-shot marketing campaigns over a thin send interface that outbound fulfils — staff-built, staff-sent, audit-tracked.
status: backlog
created: 2026-05-23T14:19:04Z
---

# PRD: campaigns

## Executive Summary

The v3 retention slice gave PlayDesk the data needed to segment customers (`Customer.tags`, `total_visits`, `last_visit_at`, `locale_pref`), and the v4 `outbound` slice (parallel) gives it the delivery pipeline to actually reach them. This epic ties the two together: staff define reusable `Segment`s ("VIPs visited in the last 60 days"), draft a `Campaign` against a segment with a templated body, preview the recipient count, and send.

To keep `campaigns` parallel-runnable with `outbound`, the send path is wired through a thin `send_campaign_message(customer, body)` interface in `backend/campaigns/send.py`. If `outbound` is in main, the implementation delegates to `outbound.enqueue_message`; otherwise a stub logs and returns success. This mirrors the v3 pattern where `multi-channel`'s SMS adapter degraded to an internal `normalize_phone()` stub when `retention` hadn't yet landed. The user-facing surface, segment evaluator, send pipeline, and audit log all ship in v4 even if `outbound` slips.

## Problem Statement

Staff today have no way to message a group of customers. "Send the regulars a heads-up about the new arcade machine" is a 30-customer manual SMS thread today. Without segmentation it's also untargeted: a re-engagement message ("we miss you!") sent to a customer who came in yesterday looks broken. The v3 retention slice exposed the right data (tags, visit recency) but never surfaced it as a query, and the parallel `outbound` slice will give us the wire but not the audience model.

Building this as a single-purpose feature ("re-engagement campaign", "VIP campaign") locks us in. A small segmentation DSL + a generic "campaign" object lets staff express new audiences without code changes.

## User Stories

- **As a store owner**, I can build a saved segment ("Lapsed VIPs — tag=vip, no visit in 90 days") with a filter builder, see how many customers match, save it, and reuse it across campaigns.
  - *Acceptance:* `/admin/segments` shows tag-chip selectors, a "min visits" field, and a "last visit older than N days" field; the preview count updates within 1s of changing a filter.
- **As staff**, I can compose a one-shot campaign — pick a segment, draft a body with `{customer.name}` placeholders, schedule for now or a future time, see the recipient count, and click Send.
  - *Acceptance:* a confirmation modal shows the exact recipient count and an excerpt of the rendered body for the first recipient; Send is disabled if the count is zero or the body is empty.
- **As a store owner**, I can open a sent campaign and see per-recipient delivery status — sent / failed / cancelled, with a failure reason when relevant.
  - *Acceptance:* `/admin/campaigns/[id]` shows a paginated `CampaignRun` table; the totals at the top match the row counts in each status bucket.
- **As a developer**, I can ship the campaigns slice and have it work in a deploy where `outbound` hasn't merged yet — the send pipeline degrades to a logging stub and the audit log still records the attempt.
  - *Acceptance:* a feature check picks the real delegate if `outbound` is importable; otherwise the stub is wired in; tests cover both paths.
- **As staff**, I cannot accidentally send the same campaign twice — once sent, the campaign is locked and re-sending requires duplicating it.
  - *Acceptance:* `Campaign.status` transitions are append-only (`draft → scheduled → sending → sent | cancelled`); the API rejects a second send with 409.

## Functional Requirements

1. **`Segment` model**:
   - `store (FK)`, `name`, `filter (JSON)`, `created_by (User FK)`, `created_at`.
   - `filter` is a small documented DSL — `{ "tags_include": ["vip"], "min_total_visits": 5, "last_visit_within_days": 60, "locale_pref": "zh" }`. All keys are optional; combined with AND.
2. **`Campaign` model**:
   - `store (FK)`, `name`, `segment (FK, on_delete=PROTECT)`, `body_template (text — `{customer.name}` placeholders rendered server-side)`, `scheduled_for (datetime — defaults to now)`, `status ('draft' | 'scheduled' | 'sending' | 'sent' | 'cancelled')`, `created_by (User FK)`, `sent_at (datetime, nullable)`, `recipient_snapshot_count (int, set at send time)`.
3. **`CampaignRun` model** — one row per recipient:
   - `campaign (FK)`, `customer (FK)`, `status ('queued' | 'sent' | 'failed' | 'skipped_optout')`, `outbound_message_id (str, nullable — set if outbound returns an id)`, `failure_reason (str, nullable)`, `created_at`, `sent_at (nullable)`.
   - Unique on `(campaign, customer)` — guarantees no double-send per (campaign, recipient).
4. **Segment evaluator** in `backend/campaigns/segments.py`:
   - `customers_for(segment: Segment) -> QuerySet[Customer]` — composes the filter dict into Django ORM `Q` predicates server-side; never loads-then-filters.
   - Supports the four DSL keys above; ignores unknown keys with a logged warning (forward-compat).
   - Always filters by `segment.store` (no cross-store leakage).
5. **Thin send interface** in `backend/campaigns/send.py`:
   - `send_campaign_message(customer, body, reference) -> SendResult` — returns `{ ok: bool, provider_message_id: str | None, reason: str | None }`.
   - Implementation picks delegate at import time: if `from outbound.api import enqueue_message` succeeds, the real delegate calls it with `template_key="campaign"` and the rendered body; otherwise the stub logs `[campaigns] stub send (outbound not installed): <reference>` and returns `{ ok: True, provider_message_id: None, reason: None }`.
   - Both code paths are unit-tested.
6. **Send pipeline** in `backend/campaigns/runner.py`:
   - `send_campaign(campaign_id)` — runs in one transaction:
     - Flips `status` to `sending`.
     - Materialises `CampaignRun` rows for every customer in `customers_for(segment)` who isn't opted out (`"sms_opt_out" not in customer.tags`); opted-out customers get a `skipped_optout` row instead.
     - Sets `recipient_snapshot_count`.
     - Commits, then iterates the runs and calls `send_campaign_message` for each, updating row status as it goes.
     - On full completion flips `Campaign.status` to `sent` and sets `sent_at`.
   - Exposed via `POST /api/admin/campaigns/{id}/send/`. Synchronous in v4 (no Celery); responses cap at 1000 recipients per campaign.
7. **Admin endpoints**:
   - `GET/POST /api/admin/segments/`, `PATCH/DELETE /api/admin/segments/{id}/`, `GET /api/admin/segments/{id}/preview/?limit=20` → `{ count, sample: [...] }`.
   - `GET/POST /api/admin/campaigns/`, `PATCH /api/admin/campaigns/{id}/` (draft only), `POST /api/admin/campaigns/{id}/send/`, `POST /api/admin/campaigns/{id}/cancel/` (draft / scheduled only).
   - `GET /api/admin/campaigns/{id}/runs/?status=failed` → paginated `CampaignRun` rows.
8. **Frontend pages**:
   - `/admin/segments` — list + create / edit modal (tag chips, visits slider, last-visit dropdown, locale dropdown). Live preview count via the preview endpoint.
   - `/admin/campaigns` — list (status chips, scheduled_for, sent count). Create flow: pick segment → preview count → write body → set schedule → confirmation modal → send.
   - `/admin/campaigns/[id]` — campaign detail: header (status, sent_at, totals), runs table (paginated, status filter).
9. **Body rendering** — same `SafeFormatter` pattern as outbound: `{customer.name}`, `{customer.locale_pref}`, `{store.name}` available; missing keys raise at send time, not in production silently.
10. **Audit log** — `Campaign.created_by` is captured on POST; the user who triggered the send is captured in a new `Campaign.sent_by (User FK, nullable)` field at send time.
11. **Confirmation safety** — the send endpoint requires `body` (already on the model) and a `confirm: true` flag in the POST body; the frontend modal sets this. Prevents accidental curls from landing.

## Non-Functional Requirements

- Segment preview p95 <500ms for a store with 50 000 customers (the four DSL filters all hit indexes already added by retention).
- Campaign send is atomic with respect to recipient snapshot — a customer added to the segment between the preview and the send is *not* sent to (snapshot is taken inside `send_campaign`).
- The opt-out check is delegated to outbound when outbound is in main (single source of truth for what "opted out" means); when outbound is absent, the stub treats `"sms_opt_out" in customer.tags` as opted out.
- One additive migration. No backfill.
- The stub / real-delegate switch happens at import time; toggling outbound's presence does not require restarting between tests (the test suite has an explicit fixture that monkeypatches the import).

## Success Criteria

- A reviewer can: build a segment ("VIPs with 3+ visits in last 30 days") → see preview count update → save → create a campaign against it → see the same count in the send modal → send → see a `Campaign.status = "sent"` with a populated `CampaignRun` table.
- When `outbound` is installed, every `CampaignRun` either gets an `outbound_message_id` (and the corresponding `OutboundMessage` exists) or is `skipped_optout`.
- When `outbound` is absent, every `CampaignRun` lands as `sent` with `outbound_message_id = NULL` and the stub log line is present.
- Attempting to send the same campaign twice returns 409 `{"error":"campaign_already_sent"}`.
- Editing a campaign after it has been sent returns 409.
- The segment preview count exactly matches the `recipient_snapshot_count` written at send time (when no customer changes intervene).

## Constraints & Assumptions

- Campaigns are *per-store* — a segment cannot include customers from another store.
- Send is synchronous in v4 (Django request thread). 1000-recipient cap is enforced server-side.
- No A/B testing of variants, no drip sequences, no rich media in v4.
- The DSL is intentionally limited to four keys — extending it requires a migration / code change, not a UI-driven free-form query (that's a future feature).
- Recipients are snapshot at send time — there is no "rolling campaign" mode where late-joining customers get a deferred send.

## Out of Scope

- A/B variant testing.
- Multi-step drip campaigns.
- Image / MMS attachments.
- Customer self-serve subscription preferences (the existing binary `sms_opt_out` tag is the only opt mechanism).
- Cross-store segments / global campaigns.
- Free-form segment query language beyond the four documented DSL keys.
- Scheduled-recurring campaigns ("send this every Monday") — only one-shot in v4.
- Webhook-based delivery-status updates (Twilio status callbacks).

## Dependencies

- Hard: `retention` (already in main) — uses `Customer`, `customer.tags`, `customer.total_visits`, `customer.last_visit_at`, `customer.locale_pref`.
- Soft: `outbound` (parallel v4 slice) — when present, `send_campaign_message` delegates to `outbound.enqueue_message`; when absent, a logging stub keeps the pipeline shippable. Adoption is a one-line import-check.
- Soft: `memberships` (parallel v4 slice) — adds a future segmentation key (`min_lifetime_points`), but not in v4 (would be a small follow-on DSL extension once both ship).
