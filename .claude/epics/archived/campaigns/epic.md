---
name: campaigns
status: completed
created: 2026-05-23T14:19:04Z
updated: 2026-05-23T16:43:38Z
progress: 100%
prd: .claude/prds/campaigns.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/119
---

# Epic: campaigns

## Overview

Add `Segment`, `Campaign`, and `CampaignRun` models, a four-key segment DSL evaluated as Django ORM `Q` predicates, a thin `send_campaign_message()` interface with an outbound-delegating impl and a stub fallback, a synchronous send pipeline that snapshots recipients into `CampaignRun` rows for audit, and an admin surface for segment-building + campaign-composition + per-recipient delivery status.

## Architecture Decisions

- **Thin send interface, two impls, picked at import time.** `backend/campaigns/send.py::send_campaign_message` is the only place campaigns talks to delivery. If `outbound.api.enqueue_message` is importable, the real impl delegates to it; otherwise a stub logs and returns success. Mirrors the v3 retention↔multi-channel pattern where `multi-channel` shipped its own `normalize_phone` stub.
- **Recipient snapshot at send time, never at draft time.** `customers_for(segment)` runs inside `send_campaign` under one transaction; rows are written to `CampaignRun` before any send happens. A customer added to the segment after send is not retroactively sent to.
- **Append-only status transitions.** `Campaign.status` only moves forward (`draft → scheduled → sending → sent | cancelled`). Re-sending a sent campaign returns 409. Editing a campaign past `draft` returns 409.
- **DSL is intentionally small.** Four keys (`tags_include`, `min_total_visits`, `last_visit_within_days`, `locale_pref`) all compile to indexed `Q` predicates. Unknown keys are logged + ignored for forward-compat, not raised — so a v5 key on a v4 deploy degrades safely.
- **Per-store isolation enforced by the evaluator.** Every query is filtered by `segment.store` before any other predicate. No request-layer check is sufficient — putting it in the evaluator means tests can call it directly without an HTTP fixture.
- **Synchronous send, capped at 1000 recipients.** v4 keeps Celery off the dependency list. The cap is enforced server-side and surfaced in the confirmation modal.

## Technical Approach

### Frontend Components
- `frontend/src/app/admin/segments/page.tsx` — list of saved segments + "new segment" modal.
- `frontend/src/components/admin/segment-builder.tsx` — the four-DSL-key builder (tag chips, visits slider, last-visit dropdown, locale dropdown). Live preview count via debounced calls to `/api/admin/segments/{id}/preview/`.
- `frontend/src/app/admin/campaigns/page.tsx` — list of campaigns (status chips, scheduled_for, sent count).
- `frontend/src/app/admin/campaigns/new/page.tsx` — create flow (pick segment → preview → body → schedule → confirmation modal).
- `frontend/src/app/admin/campaigns/[id]/page.tsx` — campaign detail (totals header + paginated `CampaignRun` table, status filter chips).
- Reuse existing `pd-*` design tokens.

### Backend Services
- `backend/campaigns/__init__.py` — new Django app.
- `backend/campaigns/models.py` — `Segment`, `Campaign`, `CampaignRun` (unique on `(campaign, customer)`).
- `backend/campaigns/migrations/0001_initial.py`.
- `backend/campaigns/segments.py` — `customers_for(segment) -> QuerySet[Customer]`; compiles the JSON DSL to `Q` predicates server-side, always store-scoped, ignores unknown keys with a logged warning.
- `backend/campaigns/send.py` — `send_campaign_message(customer, body, reference) -> SendResult`. Tries `from outbound.api import enqueue_message` at import time; binds the real or stub impl accordingly.
- `backend/campaigns/runner.py` — `send_campaign(campaign_id)`: flips status, snapshots recipients, iterates runs, calls `send_campaign_message`, updates row status. Atomic with respect to recipient snapshot.
- `backend/campaigns/rendering.py` — same `SafeFormatter` pattern as outbound; `{customer.name}`, `{customer.locale_pref}`, `{store.name}` available.
- `backend/api/views_campaigns.py`:
  - Segments: standard DRF ModelViewSet (CRUD) + `GET /api/admin/segments/{id}/preview/?limit=20`.
  - Campaigns: ModelViewSet with `partial_update` allowed only on `status == "draft"`; custom `POST /api/admin/campaigns/{id}/send/` (requires `confirm: true`) and `POST /api/admin/campaigns/{id}/cancel/`.
  - Runs: `GET /api/admin/campaigns/{id}/runs/?status=failed&page=N`.
- `backend/campaigns/tests/test_stub_vs_real.py` — fixture that monkeypatches the `outbound` import to exercise both paths in a single test run.

### Infrastructure
- No new pip deps.
- No env-var changes.
- No new cron; send is synchronous in v4.

## Implementation Strategy

Schema first. Then the segment evaluator with its own tests (decoupled from any HTTP layer). Then the thin send interface (both impls, both tested). Then the runner that ties them together. Admin endpoints + frontend in parallel afterward.

## Task Breakdown Preview

- 001 — Migration: `Segment` + `Campaign` + `CampaignRun`
- 002 — Segment evaluator (`customers_for`) + DSL parser + store-scoping + unit tests
- 003 — Thin send interface (`send_campaign_message`) — real (outbound-delegating) impl + stub fallback + import-time switch + tests for both paths
- 004 — Send pipeline (`send_campaign` runner) + status state machine + recipient snapshot + opt-out filtering
- 005 — Admin endpoints: segments CRUD + preview, campaigns CRUD + send + cancel, runs list
- 006 — Admin frontend: /admin/segments + /admin/campaigns (list + new + detail) + confirmation modal

## Dependencies

- Hard: `retention` (in main) — `Customer`, `customer.tags`, `customer.total_visits`, `customer.last_visit_at`, `customer.locale_pref`.
- Soft: `outbound` (parallel v4) — `send_campaign_message` delegates to `outbound.api.enqueue_message` if importable; otherwise the stub keeps the pipeline shippable. Adoption is one import check.
- Soft: `memberships` (parallel v4) — could add `min_lifetime_points` to the DSL; not in v4 scope.

## Success Criteria (Technical)

- Migration applies clean forward + reverse.
- `customers_for(segment)` is store-scoped by construction (verified by a test that creates two stores' customers and asserts cross-leak is impossible).
- The DSL preview matches `recipient_snapshot_count` at send time when no underlying customer change intervenes.
- Both stub and real send paths are covered by tests; toggling the outbound import does not require a process restart between tests.
- Sending the same campaign twice returns 409 `{"error":"campaign_already_sent"}`; editing past `draft` returns 409.
- Per-recipient `CampaignRun` rows reflect terminal status for every customer in the snapshot (no orphan `queued` runs after the runner completes).
- Existing backend test suite passes; ≥10 new tests cover the evaluator, DSL parser, both send impls, state-machine guards, and the per-store isolation invariant.

## Estimated Effort

- ~3 days for one developer.
- Critical path: 001 (schema) → 002 (evaluator) → 003 (send interface) → 004 (runner). 005 + 006 in parallel afterward.

## Tasks Created
- [ ] #120 - Migration: Segment + Campaign + CampaignRun (parallel: false)
- [ ] #121 - Segment evaluator + DSL parser + store-scoping (parallel: true, depends on 001)
- [ ] #122 - Thin send interface: real (outbound-delegating) + stub + import-time switch (parallel: true, depends on 001)
- [ ] #123 - Send pipeline (`send_campaign` runner) + state machine + recipient snapshot (parallel: false, depends on 002, 003)
- [ ] #124 - Admin endpoints: segments CRUD + preview, campaigns CRUD + send + cancel, runs list (parallel: true, depends on 004)
- [ ] #125 - Admin frontend: /admin/segments + /admin/campaigns + confirmation modal (parallel: true, depends on 005)

Total tasks: 6
Parallel tasks: 4
Sequential tasks: 2
Estimated total effort: 22 hours
