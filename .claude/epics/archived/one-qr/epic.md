---
name: one-qr
status: completed
created: 2026-05-23T04:27:55Z
updated: 2026-05-23T14:10:41Z
progress: 100%
prd: .claude/prds/one-qr.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/84
---

# Epic: one-qr

## Overview

`QRAction` + `QREvent` models, an admin config page at `/admin/qr` with drag-and-drop ordering, a server-rendered public landing page at `/qr/[store-slug]`, click tracking, and a small analytics endpoint. The most COSReady-distinctive feature on the public site.

## Architecture Decisions

- **Public page is SSR.** Server-render the action list, branding, and the scan event in one response — no client-side hydration race on the QR landing. Uses Next.js App Router server components.
- **Events are opportunistic, not gated.** Customer linkage is via a `pd_customer` cookie set by prior bookings; missing cookie just records an anonymous event. Never 4xx an event.
- **Click events are fire-and-forget on the wire.** Client fires `navigator.sendBeacon('/api/qr/event/', ...)` then immediately navigates to the target URL. The redirect is never blocked on the network call.
- **Store slug stable across renames.** `Store.slug` lands in this epic's migration and is generated from `name` on insert, mutable only via an explicit admin action — so the printed QR doesn't break when the store renames itself.

## Technical Approach

### Frontend Components
- `frontend/src/app/qr/[slug]/page.tsx` — public landing (server component).
- `frontend/src/app/admin/qr/page.tsx` — admin config (drag-and-drop list + analytics card row).
- `frontend/src/components/qr-action-row.tsx` — one editable action row.
- `frontend/src/components/metric-card.tsx` — shared with future slices (defined here for analytics row).

### Backend Services
- `backend/core/migrations/000X_qr_action_event.py` — `QRAction`, `QREvent`, `Store.slug`.
- `backend/api/qr_admin.py` — admin CRUD + reorder + analytics endpoint.
- `backend/api/qr_public.py` — `POST /api/qr/event/` for scan / click recording.
- `backend/core/models.py` — extend `Store` with `slug` + `brand` (JSON: logo URL, accent override).

### Infrastructure
- No new env vars.
- One additive migration. Optional second migration if `Store.slug` needs a backfill data step.

## Implementation Strategy

Migration first, then the admin config + public page can develop in parallel because they share only model types. Analytics endpoint can land alongside; the admin card row consumes it last.

## Task Breakdown Preview

- 001 — Migration: QRAction + QREvent + Store.slug + Store.brand
- 002 — Public landing page /qr/[slug] (SSR, bilingual, branded)
- 003 — Click / scan tracking endpoint /api/qr/event/ with opportunistic customer linkage
- 004 — Admin CRUD endpoints: list / create / patch (reorder) / delete
- 005 — Admin config page /admin/qr with drag-and-drop + analytics card row
- 006 — Seed data: 4 default actions on the demo store

## Dependencies

- Hard: none.
- Soft: `retention` — when `Customer` exists, click events credit points to the customer. Without it, events are anonymous and points are stored on the `QREvent` row only.

## Success Criteria (Technical)

- A scanned QR loads the public page in <1.5s on a mid-tier mobile (Network: Fast 3G in DevTools).
- Reordering in admin is reflected in the public page on the next request.
- Anonymous events do not 4xx; identified events carry the `customer_id` when the cookie is present.
- Per-action breakdown sums to the total click count.
- ≥6 new tests cover the public page render, click endpoint, admin CRUD, reorder, and analytics shape.

## Estimated Effort

- ~3 days for one developer.
- 001 (schema) is the only hard prerequisite. 002 / 003 / 004 in parallel after that. 005 last (it links them).

## Tasks Created
- [ ] 001.md - Migration: QRAction + QREvent + Store.slug + Store.brand (parallel: false)
- [ ] 002.md - Public landing page /qr/[slug] (SSR + bilingual + branded) (parallel: true)
- [ ] 003.md - Click / scan tracking endpoint with opportunistic customer linkage (parallel: true)
- [ ] 004.md - Admin CRUD: list / create / reorder / delete (parallel: true)
- [ ] 005.md - Admin config page /admin/qr with drag-and-drop + analytics cards (parallel: false, depends on 004)
- [ ] 006.md - Seed data: 4 default actions on the demo store (parallel: true)

Total tasks: 6
Parallel tasks: 5
Sequential tasks: 1
Estimated total effort: 20 hours
