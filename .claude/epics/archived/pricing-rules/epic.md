---
name: pricing-rules
status: completed
created: 2026-05-24T04:00:00Z
updated: 2026-05-24T11:50:00Z
progress: 100%
prd: .claude/prds/pricing-rules.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/172
---

# Epic: pricing-rules

## Overview

A small rule-evaluation pipeline that replaces today's `Resource.hourly_rate * hours` with a `(resource, start, end, customer) → Quote` function. Rules are configured per-store in admin, evaluated at quote time, and frozen on `Booking.total_amount` + `Booking.rule_snapshot` at booking creation. Five rule types ship (peak_hours, day_of_week, member_tier, min_duration, bracket_rate); adding a sixth is one new `RuleStrategy` subclass + registry entry.

## Architecture Decisions

- **Strategy pattern over a giant `if rule_type == ...` chain.** Each rule type lives in its own file under `backend/pricing/strategies/`. Registry is a dict literal in `__init__.py`. Adding a new type means writing one file + one line. The engine itself has no knowledge of any specific rule type.
- **JSON params per rule, not a dedicated table per rule type.** Five rule types now, plausibly 10 by end of year. A dedicated table per type would force a migration per addition. A single `params: JSONField` plus per-strategy validation is the right trade-off at this scale.
- **Quote frozen on `Booking` at creation, not recomputed on read.** Historical bookings stay deterministic; a rule change today doesn't rewrite yesterday's revenue. `rule_snapshot` is the audit trail — every line item that fired, captured.
- **No promo codes in v8.** Adjacent feature, separate fraud surface (redemption tracking, expiry, one-time-use). Earned its own future epic.
- **Decimal arithmetic throughout; no floats.** Round only at final total. Engine takes Decimal in, returns Decimal out.
- **Stackability via a simple `stackable: bool` flag, not a precedence matrix.** Non-stackable rules block subsequent non-stackable rules. Stackable rules always apply. Two-tier model covers ~95% of real-world pricing without growing into a constraint solver.
- **Optimistic-concurrency on quote → booking-create.** Client passes `expected_total_amount`; recompute on the server; mismatch returns 409 with the new quote. Race window (rule edit between quote and submit) is tiny but real.

## Technical Approach

### Frontend Components
- `frontend/src/app/admin/pricing/page.tsx` (new) — list of rules with priority drag-handle, enable/disable toggle, new/edit/delete actions.
- `frontend/src/app/admin/pricing/RuleForm.tsx` (new) — dynamic form per `rule_type` (params shape differs).
- `frontend/src/app/admin/pricing/QuoteSandbox.tsx` (new) — "test this rule" sandbox: pick resource + time + tier → see quote breakdown without saving.
- `frontend/src/app/s/[slug]/book/BookingPage.tsx` — augment the existing booking page to fetch + display quote line items below the time picker.
- `frontend/src/app/admin/bookings/[id]/page.tsx` (or wherever booking detail lives) — show frozen `total_amount` + `rule_snapshot` breakdown.

### Backend Services
- `backend/pricing/` (new Django app) — `models.py` (`PricingRule`), `engine.py` (`compute_quote`), `strategies/` (one file per rule_type + `__init__.py` with `RULE_REGISTRY`), `serializers.py`, `views.py` (Quote endpoint + admin CRUD).
- `backend/core/migrations/000X_booking_pricing_fields.py` (new) — `Booking.total_amount`, `Booking.rule_snapshot`, `Booking.refund_amount` (placeholder for v9).
- `backend/core/migrations/000Y_backfill_booking_total_amount.py` (new) — backfill: `total_amount = resource.hourly_rate * hours`, `rule_snapshot = []`.
- `backend/api/views_public.py` — booking-create endpoint wraps `compute_quote(...)` + freezes onto the row.
- `backend/agent_tools/tools.py` — `check_availability` returns quoted prices per slot; `get_resource_details` returns `hourly_rate` + "starting from" text.
- `backend/config/urls.py` — wire `/api/quote/` + `/api/admin/pricing-rules/`.

### Infrastructure
- New Django app `pricing` added to `INSTALLED_APPS`.
- Two additive migrations on `core.Booking`; one initial migration in `pricing`.

## Implementation Strategy

Tasks 173 (engine) and 174 (Booking augmentation) can land in parallel — they touch different files and the engine doesn't need the Booking changes to work. 175 (quote API + agent tool) depends on 173. 176 (booking-create wiring) depends on both 173 and 174. 177 (admin UI + customer-page quote display) depends on 175 + 176.

Single agent, mostly sequential because the agent loop is one-thread. Estimated wall-time: 30–60 min.

## Task Breakdown Preview

- 173 — `PricingRule` model + `RuleStrategy` ABC + 5 strategies (peak_hours, day_of_week, member_tier, min_duration, bracket_rate) + registry + per-strategy unit tests
- 174 — `Booking.total_amount` / `rule_snapshot` / `refund_amount` migration + backfill + serializer fields
- 175 — `compute_quote` engine + `Quote` dataclass + `POST /api/quote/` endpoint + `check_availability` tool update
- 176 — Booking-create wires `compute_quote(...)` + freezes onto row + 409 on `expected_total_amount` mismatch
- 177 — Admin `/admin/pricing/` page (list + dynamic form + sandbox) + booking-page quote breakdown + admin booking-detail rule_snapshot display

## Dependencies

- Hard: `multi-location` (v6, in main) — rules are store-scoped via `request.store`.
- Hard: `memberships` (v4, in main) — `member_tier` rule reads from `RewardTier`.
- Hard: `backend-core` (v2, in main) — `Resource`, `Booking`, `hourly_rate`.

## Success Criteria (Technical)

- Existing backend test suite passes after migration + backfill (every existing test was created in a world with zero rules; the engine returns base price when no rules exist).
- New tests in `pricing/tests/test_engine.py`: each strategy fires correctly in isolation; stackability ordering; non-stackable exclusion; floor-at-zero; decimal precision.
- New test in `tests/test_booking_create_quote.py`: race-condition simulation — quote → rule-add → submit returns 409 with new quote.
- Agent tool `check_availability` integration test: returns quoted prices after a peak_hours rule is configured.
- Quote API returns < 50ms for a store with 50 rules (perf assertion in test_engine_perf.py).

## Estimated Effort

- Single agent, ~30–60 min wall-time.

## Tasks Created
- [ ] #173 - PricingRule model + RuleStrategy ABC + 5 strategies + registry (parallel: false)
- [ ] #174 - Booking.total_amount/rule_snapshot/refund_amount migration + backfill (parallel: true)
- [ ] #175 - compute_quote engine + Quote dataclass + /api/quote/ + check_availability tool update (parallel: false, depends on 173)
- [ ] #176 - Booking-create wires compute_quote + freezes onto row + 409 on mismatch (parallel: false, depends on 173, 174)
- [ ] #177 - Admin /admin/pricing/ page + booking-page quote breakdown + admin booking-detail (parallel: false, depends on 175, 176)

Total tasks: 5
