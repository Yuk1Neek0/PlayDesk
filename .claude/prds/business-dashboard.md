---
name: business-dashboard
description: A unified business-metrics card row on /admin — bookings, revenue, new customers, outbound sent, QR engagement — replacing today's per-feature analytics with a single business-owner view.
status: backlog
created: 2026-05-24T01:00:22Z
---

# PRD: business-dashboard

## Executive Summary

PlayDesk's `/admin` page today shows "Tonight at PlayDesk" + an "All bookings" list. Per-feature analytics exist (`/admin/qr` shows scans/clicks/engagement) but a store owner cannot answer the basic question "is my business healthy this week" without clicking through five pages. COSReady's public site lists "business dashboard" and "analytics and reports" as separate first-class surfaces.

This epic adds a top-of-page metric strip on `/admin` that aggregates across the v3 / v4 surfaces into one read: today's bookings, this-month revenue, new customers in the last 30 days, outbound messages sent in the last 24 hours, and QR engagement rate. Backed by a single composite endpoint so the dashboard loads in one round-trip.

## Problem Statement

A store owner looking at the existing `/admin` page sees individual bookings but no health signal. They have to:
- Count tonight's bookings by eye
- Open `/admin/qr` to see scan engagement
- Open `/admin/customers/[id]` to see if customers are returning (no roll-up exists)
- Have no way at all to see this-month revenue or outbound message volume

The data exists — `Booking`, `Customer`, `OutboundMessage`, `QREvent`, and (once Stripe is fully wired) `Booking.deposit_amount` all sit on the same per-store schema. The aggregation just hasn't been done.

## User Stories

- **As a store owner**, when I open `/admin` the first thing I see is a metrics strip telling me bookings today, revenue this month, new customers in the last 30 days, and outbound messages sent in the last 24 hours.
  - *Acceptance:* the strip renders above the existing "Tonight at PlayDesk" section in <300ms on initial page load.
- **As a store owner**, I see QR engagement on the same screen — total scans + total clicks in the last 7 days, with engagement rate as the headline.
  - *Acceptance:* the QR card mirrors the existing `/admin/qr` card design but lives in the dashboard strip.
- **As a store owner**, each metric is clickable and deep-links to the relevant detail page (e.g. revenue card → `/admin/bookings?status=completed`, customers card → `/admin/customers`).
- **As a developer**, the dashboard's metrics come from a single endpoint — no N+1 of per-card fetches.

## Functional Requirements

1. **Composite metrics endpoint** `GET /api/admin/metrics/business/?days=N` (default `days=30`) returning:
   ```json
   {
     "bookings_today": { "count": int, "trend_pct_vs_yesterday": float | null },
     "bookings_window": { "count": int, "window_days": int },
     "revenue_window": { "amount_cents": int, "currency": "CAD", "window_days": int },
     "new_customers_window": { "count": int, "window_days": int },
     "outbound_24h": { "sent": int, "failed": int, "queued": int },
     "qr_window": { "scans": int, "clicks": int, "engagement_pct": float, "window_days": 7 }
   }
   ```
2. **`bookings_today.count`** — `Booking.objects.filter(start_time__date=today_local)`. `trend_pct_vs_yesterday` is a percentage delta vs the previous day; `null` if yesterday had zero bookings (avoid divide-by-zero noise).
3. **`bookings_window.count`** — bookings whose `start_time` falls in the last `days` days.
4. **`revenue_window.amount_cents`** — `SUM(Booking.deposit_amount)` for completed bookings in the window. If `deposit_amount` isn't populated (Stripe not configured), defaults to `0` with `currency="CAD"`. Documented behaviour.
5. **`new_customers_window.count`** — `Customer.objects.filter(created_at__gte=...).count()` over the window.
6. **`outbound_24h`** — aggregate counts of `OutboundMessage` rows created in the last 24h by status.
7. **`qr_window`** — total `QREvent.kind='scan'` + total `QREvent.kind='click'` in the last 7 days (window hard-pinned for engagement to be meaningful); engagement = `clicks / scans * 100`, or `0.0` if `scans == 0`.
8. **Frontend metric strip** on `/admin/page.tsx`:
   - Six cards in a responsive grid (wraps to two rows on mobile).
   - Each card: big number + label + tiny trend chip + click-target deep-link.
   - Loading skeleton on first render; updates on a 60-second poll while the page is open.
   - Reuses existing `pd-stat` / `pd-card` design tokens — no new CSS file.
9. **Time-zone correctness** — `bookings_today` is in store-local time (America/Toronto), NOT UTC. Matches the v3 timezone fix.
10. **Per-store scoping** — single-store v5 returns the default store's metrics. Multi-location store-switcher is v6.

## Non-Functional Requirements

- The composite endpoint returns in <300ms on a store with 10 000 bookings + 100 000 QREvents (covered by an `EXPLAIN ANALYZE` regression test).
- The endpoint is one query plan: a handful of `aggregate()` calls in one transaction, no per-row iteration.
- Polls do not stack — a slow response cancels in-flight polls before issuing a new one.
- Card-click deep-links use existing admin routes; no new admin pages.
- Cache headers on the endpoint: `Cache-Control: private, max-age=30` (mild caching for the polling case).

## Success Criteria

- A reviewer can open `/admin` on the demo store and see all six cards populated within 1 second of page load.
- Changing `bookings_today` by creating a booking through the agent reflects on the dashboard within one poll tick (60s).
- The endpoint passes a perf test (`<300ms p95` over a 10 000-booking seed).
- Existing `/admin` page layout is preserved (the strip is additive, above the "Tonight at PlayDesk" section).
- Existing Playwright admin tests pass unchanged.

## Constraints & Assumptions

- Single-store v5 — multi-location aggregation is v6.
- `revenue_window` uses `Booking.deposit_amount` populated by the Stripe path; without Stripe configured, revenue shows `0` with no error.
- Trends and engagement are computed server-side, not client-side; the response is a final-form display struct.
- No customisation of which metrics show up — fixed six-card layout in v5.

## Out of Scope

- Customisable dashboard layout / drag-and-drop cards.
- Time-series charts / sparklines (just numbers in v5).
- Export to CSV / PDF.
- Per-staff-member dashboards (single store-owner view).
- Multi-location aggregation — v6.
- Email digest of the dashboard.

## Dependencies

- Hard: `retention` (in main) — `Customer` model + `created_at`.
- Hard: `one-qr` (in main) — `QREvent` model.
- Hard: `outbound` (in main) — `OutboundMessage` model.
- Hard: `enhancements` (in main) — `Booking.deposit_amount` from the Stripe slice.
- No dependencies on other v5 slices.
