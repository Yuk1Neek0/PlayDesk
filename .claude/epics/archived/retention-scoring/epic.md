---
name: retention-scoring
status: completed
created: 2026-05-24T15:30:00Z
updated: 2026-05-24T16:05:00Z
progress: 100%
prd: .claude/prds/retention-scoring.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/209
---

# Epic: retention-scoring

## Overview

Lightweight retention layer over the v4-established `Customer` signals. Adds three computed columns (`churn_score`, `cohort`, `retention_updated_at`), a nightly sweeper that recomputes them, a cohort filter on the admin customer list, one re-engagement SMS template, a bulk-send action button, and a one-line extension to the v11b agent system prompt to surface cohort. Deterministic deduction from existing data — no ML, no scheduled drips.

## Architecture Decisions

- **Deterministic cohort rules, not ML.** A 30-line function with `if/elif` thresholds is explainable, testable, and adequately accurate for this product scale. ML would need data we don't have (engagement labels, multi-week training set) and would obscure the bucket logic.
- **Sweeper as a management command, not a Celery beat task.** Project has no broker; cron is enough. Idempotent + safe to run multiple times.
- **Computed fields, not a view.** Storing the cohort lets the admin list filter use a `db_index=True` btree lookup (fast). Computing on-the-fly per row read would require complex WHERE clauses or a recursive CTE.
- **Bulk-send is a one-shot, not a saved campaign.** Saved campaigns are v4's territory. v11c's bulk-send is a thin wrapper over the current customer-list filter — staff click "send to all visible", outbound enqueues each respecting opt-out.
- **No per-store cohort thresholds in v11c.** Chains needing custom thresholds (a kids' party venue might consider "30 days dormant" different from an esports venue) fork the function. Per-store config is a v12 nicety, not a v11c need.
- **`churn_score` is monotonic-ish but not strictly so.** A customer with 50 visits going dark for 30 days scores higher than a 2-visit customer at 30 days — by design. The score is a sort key for "who should we reach out to first", not a probability.

## Technical Approach

### Backend Services
- `backend/core/models.py::Customer` — add `churn_score` (Float, db_index), `cohort` (Char choices, db_index), `retention_updated_at` (DateTime, null).
- `backend/core/retention.py` (new) — pure functions `compute_cohort(customer, now=None)`, `compute_churn_score(customer, now=None)`. Zero DB queries beyond the row itself.
- `backend/core/management/commands/recompute_retention.py` (new) — iterates customers, updates fields, logs distribution + delta vs previous run.
- `backend/api/views_admin.py::AdminCustomerListView` (extend) — accepts `?cohort=<value>` query param + returns per-cohort counts in the list response.
- `backend/outbound/templates.py` (extend) — add `re_engagement_60d` to `TEMPLATES`.
- `backend/api/views_admin.py` — new endpoint `POST /api/admin/customers/bulk-send/` body `{cohort, template_key}` → enqueues outbound per matching customer (respecting opt-out + quiet hours).
- `backend/agent/loop.py::_build_customer_context` (1-line extension) — add `- Cohort: {customer.cohort}` line when present.

### Frontend Components
- `frontend/src/app/admin/customers/page.tsx` — add cohort filter dropdown (counts inline per cohort) + bulk-send button when filter active.
- `frontend/src/components/admin/cohort-chip.tsx` (new, small) — colored chip for cohort labels reused in list + detail.

### Infrastructure
- One additive migration on `core.Customer`.
- No new pip / npm deps.

## Implementation Strategy

Sequential within the epic — each step builds on the prior:

1. **#210 Schema** — three fields + migration. Backfill happens on first sweeper run.
2. **#211 Retention logic + sweeper** — `compute_cohort` + `compute_churn_score` + management command + tests. Standalone — can be run + verified before any UI surfaces.
3. **#212 Admin surfaces + template + bulk-send** — list filter + counts chip + `re_engagement_60d` template + bulk-send endpoint + bulk-send button.
4. **#213 Agent prompt + e2e** — 1-line extension to `_build_customer_context` + e2e covering filter + bulk-send + cohort visibility in admin.

Single agent, ~30-45 min wall-time (smaller than v11a).

## Task Breakdown Preview

- 210 — Customer.churn_score + cohort + retention_updated_at + migration
- 211 — core/retention.py (compute_cohort + compute_churn_score) + recompute_retention command + tests
- 212 — Admin customer list cohort filter + counts chip + re_engagement_60d template + bulk-send endpoint + button
- 213 — Agent _build_customer_context adds cohort line + retention.e2e.ts

## Dependencies

- Hard: `retention` (v4, in main) — `Customer.total_visits`, `last_visit_at` (already signal-maintained).
- Hard: `outbound` (v4, in main) — template registry + enqueue path + opt-out + quiet hours.
- Hard: `multi-location` (v6, in main) — store scoping on customer list + sweeper.
- Soft: `v11b customer-context` (in main, just shipped at da4374a) — `_build_customer_context` exists to extend.

## Success Criteria (Technical)

- Existing 739-test backend suite passes after migration.
- New tests in `tests/test_retention.py`: each cohort threshold + churn-score math + sweeper idempotency + per-store filter.
- Sweeper finishes < 30s for 10k synthetic customers (perf test in the file).
- Bulk-send respects `sms_opt_out` tag (skips opted-out customers; logs the skip).
- Admin filter returns correct count when toggled across all 5 cohorts.
- Agent prompt block, post-extension, includes the cohort line for resolved customers.

## Estimated Effort

- Single agent, ~30-45 min wall-time.

## Tasks Created
- [ ] #210 - Customer.churn_score + cohort + retention_updated_at + migration (parallel: false)
- [ ] #211 - core/retention.py + recompute_retention management command + tests (parallel: false, depends on 210)
- [ ] #212 - Admin cohort filter + re_engagement_60d template + bulk-send endpoint + button (parallel: false, depends on 211)
- [ ] #213 - Agent prompt cohort line + retention.e2e.ts (parallel: false, depends on 212)

Total tasks: 4
