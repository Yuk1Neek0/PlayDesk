---
name: business-dashboard
status: completed
created: 2026-05-24T01:00:22Z
updated: 2026-05-24T02:03:46Z
progress: 100%
prd: .claude/prds/business-dashboard.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/142
---

# Epic: business-dashboard

## Overview

One new composite admin endpoint (`/api/admin/metrics/business/`), one new frontend metric strip on `/admin`, six metric cards backed by per-feature aggregates over the v1 / v3 / v4 models. Reads only — no migrations, no signals, no model changes.

## Architecture Decisions

- **Composite endpoint, not six per-card endpoints.** The dashboard's read shape is fixed (six known cards). Splitting into six endpoints would mean six round-trips, six points of polling-skew, and six places to add per-store scoping for v6. One endpoint is one query plan and one polling unit.
- **Each metric is a Django `aggregate()` call, not Python-side iteration.** A 10 000-row booking table cannot be loaded into Python every 60 seconds. Each card maps to one `aggregate()` or one `count()`; total six aggregates per endpoint call.
- **Time-zone correctness is delegated to a helper.** `today_local()` in store-local time, used by the `bookings_today` calculation, lives in `core/dates.py` (or extends the existing v3 timezone helper) so the dashboard cannot diverge from the rest of the app's tz handling.
- **Mild caching on the response** (`Cache-Control: private, max-age=30`). The dashboard polls every 60s; cache absorbs accidental refreshes without trading much freshness.
- **Single-store v5.** The endpoint returns the default store's metrics. The query factors the store filter into a single `Store.objects.first()` lookup the same way the rest of the app does; v6 will replace that with a current-store context.

## Technical Approach

### Frontend Components
- `frontend/src/components/admin/business-dashboard-strip.tsx` (new) — six `<MetricCard />` components in a responsive `pd-grid`. Each card: big number + label + trend chip + click-target deep-link.
- `frontend/src/components/admin/metric-card.tsx` (new) — small reusable card. Variants: number-only, number-with-trend, number-with-secondary.
- `frontend/src/app/admin/page.tsx` — mounts `<BusinessDashboardStrip />` above the existing "Tonight at PlayDesk" section.
- `frontend/src/lib/api.ts` — add `adminGetBusinessMetrics(days?: number): Promise<BusinessMetricsPayload>` typed against the new endpoint.
- The strip polls every 60s; cancels in-flight polls before issuing a new one.

### Backend Services
- `backend/api/views_metrics.py` (new) — `BusinessMetricsView(APIView)`:
  - `GET /api/admin/metrics/business/?days=N` (default 30).
  - Composite payload (see PRD).
  - One DB transaction; each metric is a single aggregate query.
- `backend/api/urls.py` — register the new route.
- `backend/api/serializers_metrics.py` (new, small) — serializer that shapes the composite payload.
- `backend/core/dates.py` (new or extended) — `today_local(store) -> date` returning the date in the store's timezone (America/Toronto for the default store).

### Infrastructure
- No new env vars, no new pip deps, no migration.

## Implementation Strategy

Endpoint first (with each aggregate covered by its own unit test against seeded data), then the frontend helper, then the strip + cards in parallel. The strip's render is independent of the metric-card refactor — they can land in either order.

## Task Breakdown Preview

- 001 — `today_local(store)` helper + tests (in `core/dates.py`; or extend the existing tz helper)
- 002 — `BusinessMetricsView` endpoint + per-aggregate tests + perf test (`EXPLAIN ANALYZE` regression)
- 003 — `adminGetBusinessMetrics` typed client + `BusinessMetricsPayload` type
- 004 — `<MetricCard />` reusable component + vitest test
- 005 — `<BusinessDashboardStrip />` composite + polling logic + mount on `/admin`

## Dependencies

- Hard: `retention` (in main) — `Customer.created_at`.
- Hard: `one-qr` (in main) — `QREvent` model.
- Hard: `outbound` (in main) — `OutboundMessage` model.
- Hard: `enhancements` (in main) — `Booking.deposit_amount` from Stripe slice.
- Soft: none. Independent of other v5 slices.

## Success Criteria (Technical)

- The endpoint returns in <300ms on a seeded 10 000-booking + 100 000-QREvent dataset (perf test).
- All six metrics produce the right numbers against seeded test data (one assertion per metric).
- The strip renders all six cards within 1 second of `/admin` page load.
- Click-target deep-links navigate to the documented admin routes (e.g. revenue → `/admin/bookings?status=completed`).
- The Playwright `admin.e2e.ts` tests pass unchanged (the strip is additive above the existing layout).
- Time-zone correctness: `bookings_today` matches store-local "today" (America/Toronto), not UTC — verified by a unit test that runs at a UTC time that differs from store-local.

## Estimated Effort

- ~1 day total wall-time as a single agent. Critical path: 001 → 002 → 003 → {004, 005}.

## Tasks Created
- [ ] #143 - today_local(store) helper + tests (parallel: false)
- [ ] #144 - BusinessMetricsView endpoint + per-aggregate tests + perf regression (parallel: false, depends on 001)
- [ ] #145 - adminGetBusinessMetrics typed client + payload type (parallel: false, depends on 002)
- [ ] #146 - <MetricCard /> reusable component + vitest test (parallel: true, depends on 003)
- [ ] #147 - <BusinessDashboardStrip /> composite + 60s polling + mount on /admin (parallel: true, depends on 003)

Total tasks: 5
Parallel tasks: 2
Sequential tasks: 3
