---
name: retention-scoring
description: Lightweight retention scoring + cohort assignment for every Customer. Nightly sweeper computes `churn_score` (0-1) and `cohort` (new/active/at_risk/dormant/lost) per customer from booking history. Admin customer list gains a cohort filter. New `re_engagement_60d` outbound template lets staff (or campaigns) target dormant customers with a discount nudge. Builds on v4 retention which established total_visits + last_visit_at.
status: backlog
created: 2026-05-24T15:30:00Z
---

# PRD: retention-scoring

## Executive Summary

PlayDesk has rich retention raw data: `Customer.total_visits`, `Customer.last_visit_at`, full `Booking` history, `Payment` records (v9), conversation history. **None of it is summarized into a usable retention signal.** Staff who want to "find dormant Gold-tier customers" today have to write a SQL query or eyeball the customer list.

This epic adds two computed fields to `Customer` — `churn_score` (float, 0-1) and `cohort` (categorical) — plus a nightly sweeper to recompute them, a cohort filter on the admin customer list, and one re-engagement SMS template. Lean by design: this is the data layer + minimal surfacing, not marketing automation. Drip campaigns / A/B testing / ROI dashboards are deliberately out of scope.

This builds on v4 retention (which established the `Customer` model + `total_visits` + `last_visit_at` signal-maintenance). v4 created the raw data; v11c derives the labels.

## Problem Statement

Concretely:

- **No cohort visibility.** A staff member opens `/admin/customers/` and sees rows sorted by `last_visit_at`. They cannot answer "how many of our customers have gone dormant?" without manual counting.
- **No churn signal.** The agent (post-v11b) sees `total_visits` and `last_visit_at` in its prompt, but there's no derived "this customer is slipping" field. Without it, the agent can't soften tone for at-risk customers or hand off to staff for dormant ones.
- **No automated re-engagement trigger.** The existing campaign system (v4) can target ad-hoc segments, but there's no "every customer who became dormant this week" canned segment. Re-engagement is a manual marketing task.
- **No persistent labels.** "Lost" / "VIP" / "Regular" exist only in staff heads or `Customer.tags` (free-form). Different staff use different vocabulary.

The fix is a small data layer addition: two computed fields, a nightly sweeper, a filter, a template. Surfaces hook in mechanically.

## User Stories

- **As a chain owner**, I open `/admin/customers/?cohort=dormant` and see exactly the customers who haven't visited in 60-90 days. I can click "Send re-engagement message" to fire the `re_engagement_60d` template at the visible segment.
- **As a staff member**, when a customer messages the agent (post-v11b), the system prompt now includes "Cohort: at_risk" alongside the other profile fields. The agent's tone naturally adjusts.
- **As an operations manager**, the nightly cron prints the cohort distribution: "active: 412 (+12), at_risk: 88 (-3), dormant: 47 (+5), lost: 109". I see trends without needing a dashboard.
- **As a developer**, adding a new cohort (e.g. "vip_recent_drop") is a 10-line addition to one function.
- **As a customer in the dormant cohort** with `sms_opt_out` NOT set, I might receive a re-engagement SMS: "Hi Alice, it's been a while! Come back and we'll comp your next hour. Reply YES to book."

## Functional Requirements

1. **`Customer` model augmentation**:
   - `churn_score: FloatField(default=0.0, db_index=True)` — 0 (fully engaged) to 1 (lost).
   - `cohort: CharField(max_length=16, choices=[("new","New"),("active","Active"),("at_risk","At risk"),("dormant","Dormant"),("lost","Lost")], default="new", db_index=True)`
   - `retention_updated_at: DateTimeField(null=True)` — when the sweeper last computed.
2. **Migration**: additive, with backfill via the first sweeper run.
3. **Cohort computation** in `core/retention.py`:
   - `compute_cohort(customer, now=None) -> str`:
     ```
     days_since = (now - last_visit_at).days if last_visit_at else None
     if total_visits == 0 and (now - created_at).days < 7:
         return "new"
     if days_since is None or days_since > 90:
         return "lost"
     if days_since > 60:
         return "dormant"
     if days_since > 30:
         return "at_risk"
     return "active"
     ```
   - `compute_churn_score(customer, now=None) -> float`:
     - `days_since / 90.0` clamped to [0, 1] for the baseline.
     - Adjust by visit frequency: a customer with 50 lifetime visits going dark for 30 days is more concerning than a 2-visit customer — multiply baseline by `min(2.0, total_visits / 10)` if `total_visits >= 5`.
     - Floor at 0, ceiling at 1.
4. **Nightly sweeper** `python manage.py recompute_retention`:
   - Iterates every `Customer` row, updates `cohort` + `churn_score` + `retention_updated_at`.
   - Logs cohort distribution + delta vs the previous run.
   - Options: `--dry-run`, `--store SLUG`.
   - Idempotent; safe to re-run.
   - Suggested cron pattern in command docstring.
5. **Admin customer list filter**:
   - Backend: `AdminCustomerListView` accepts `?cohort=new|active|at_risk|dormant|lost`.
   - Frontend: dropdown filter chip on `/admin/customers/` page. Counts per cohort visible in chip ("Dormant (47)").
6. **`re_engagement_60d` outbound template**:
   - Add to `outbound/templates.py`.
   - EN: `"Hi {customer_name}, it's been a while! Come back this week and we'll comp your first hour. Reply YES to book — or skip if you're set."`
   - ZH: equivalent.
7. **Agent prompt extension** (small follow-on to v11b):
   - `_build_customer_context` in `agent/loop.py` adds a `- Cohort: {cohort}` line.
   - One-line addition.
8. **Bulk-send action** (lean, not full campaigns):
   - Admin customer list page: when a cohort filter is active, show "Send `re_engagement_60d` to all visible (47)" button. On click, enqueues outbound messages for each, respecting `sms_opt_out` tag + the existing v4 outbound rate limits + quiet hours.
   - Not a saved campaign (that's v4 campaigns territory); just a one-shot blast against the current view.

## Non-Functional Requirements

- **Cheap per-customer compute**: cohort calc is pure Python. Sweeper for 10k customers finishes in < 30s.
- **Backward compat**: existing tests pass. New fields default cleanly; sweeper backfills on first run.
- **No new pip / npm deps.**
- **Privacy**: re-engagement SMS respects `sms_opt_out` tag + v4 outbound quiet hours.
- **Audit**: bulk-send action writes a `CustomerNote(author=request.user, body="Sent re_engagement_60d via bulk action")` per customer hit.

## Dependencies

- v4 outbound (in main) — SMS adapter + template registry + opt-out + quiet hours.
- v4 retention (in main) — `Customer.total_visits` + `last_visit_at` already maintained.
- v4 memberships (in main) — tier_for() pattern.
- v6 multi-location (in main) — store scoping on customer list + sweeper.
- v11b customer context (in main, just shipped) — small extension to inject cohort.

## Out of Scope

- Scheduled / drip campaigns.
- A/B testing infra.
- ROI / revenue-attribution dashboards.
- Predictive ML scoring (deterministic rules only).
- Per-cohort tier-specific bulk actions.
- Email channel for re-engagement (SMS only).
- Customer-facing retention surface.

## Expected Conflict Zones with Peer Epic (v11a rotating-checkin)

- Both add migrations to `core` — additive, merge migration if numbers collide.
- `Customer` model: you write new fields; v11a only reads.
- `seed_data.py`: v11a seeds rotating-key. You may backfill `cohort` for seeded customers. Different sections — keep-both merge.
- Admin pages: v11a adds settings page, you add customer-list filter. Different pages.
- Outbound templates: you add `re_engagement_60d`. v11a doesn't touch templates.
