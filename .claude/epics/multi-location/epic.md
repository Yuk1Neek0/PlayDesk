---
name: multi-location
status: backlog
created: 2026-05-24T02:12:13Z
updated: 2026-05-24T02:17:33Z
progress: 0%
prd: .claude/prds/multi-location.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/157
---

# Epic: multi-location

## Overview

One Django middleware (`CurrentStoreMiddleware`), one new FK (`Conversation.store`), one admin store-switcher component + React context, one new Next.js route segment (`/s/[slug]/book`), a few `Store.objects.first()` → `request.store` swaps across ~15 admin views, and a seed of a second demo store. Sequential epic — every task builds on the previous because the swap from "implicit single store" to "explicit request.store" can't be partial without leaving the app in an inconsistent state.

## Architecture Decisions

- **Middleware-based context, not view-mixin.** The current store resolves once per request from header / cookie / URL kwarg, lives on `request.store`, and every view reads from there. A mixin would mean every admin ViewSet inherits it and the mixin pollutes per-view code; middleware is one file that every view sees for free. Mirrors the existing v3 admin-auth gate which is also middleware.
- **Backward-compat by fallback, not by feature flag.** When no header / cookie / URL slug is present, the resolver picks the alphabetically-first store. So existing single-store deployments and bookmarked URLs all keep working without any feature-flag dance. The "is this multi-store deployment" question never needs to be asked anywhere in code.
- **`Conversation.store` is the single source of truth for the agent.** The agent loop reads `conversation.store` to scope tool calls. Inbound webhooks set it at conversation creation. This avoids threading `request.store` through five layers of agent / tool / model code.
- **Single-store-at-a-time admin in v6.** No "All Stores" aggregate mode. Cross-store rollup is a hard problem (timezone normalisation, currency aggregation, ownership questions) that's worth its own epic. v6 ships the foundation; v7+ adds the aggregate view.
- **Customer-facing URL change is additive, not destructive.** `/` becomes a 302 redirect to `/s/<default>/book` rather than being removed. Existing QR cards printed with the old URL keep working.
- **`Store.slug` already exists** (added in the v3 one-qr slice for `/qr/[slug]`). v6 generalises that slug as the multi-location URL key. No new field on Store.

## Technical Approach

### Frontend Components
- `frontend/src/lib/store-context.tsx` (new) — `StoreContext` React provider + `useCurrentStore()` hook. Holds the current store's `{id, slug, name}` and a `setStore(slug)` action that writes both `localStorage` and the `pd_store_slug` cookie.
- `frontend/src/lib/admin-fetch.ts` (new) — small wrapper around `fetch` that auto-adds the `X-PD-Store-Slug` header from the current StoreContext. Used by all admin pages instead of bare `fetch`.
- `frontend/src/components/admin/store-switcher.tsx` (new) — chip-group selector in the admin nav header. Replaces the hardcoded "DOWNTOWN · TORONTO" string with the current store's name.
- `frontend/src/app/admin/layout.tsx` — wrap the admin layout in `<StoreProvider>` + mount `<StoreSwitcher />` in the header.
- `frontend/src/app/s/[slug]/book/page.tsx` (new) — mirrors today's `app/page.tsx` but receives `params.slug`, passes it through to the booking API.
- `frontend/src/app/s/[slug]/book/BookingPage.tsx` — client component (renamed from today's `app/BookingPage.tsx`).
- `frontend/src/app/page.tsx` — replaced with a server-side 302 redirect to `/s/<default-slug>/book`.
- Every existing admin page (`/admin/page.tsx`, `/admin/customers/page.tsx`, etc.) — refactor data fetches to use the new `adminFetch` wrapper. Mechanical, ~10 files.

### Backend Services
- `backend/core/middleware.py::CurrentStoreMiddleware` (new) — request resolver. Sets `request.store`. Header → cookie → URL kwarg → fallback. Side-effect: sets the cookie if the header was used (so cross-tab nav keeps the same store).
- `backend/config/settings.py` — register the middleware (after `AuthenticationMiddleware`, before any view).
- `backend/core/migrations/000X_conversation_store.py` (new) — add `Conversation.store` FK, nullable initially.
- `backend/core/migrations/000Y_backfill_conversation_store.py` (new) — data migration backfilling per the heuristic in the PRD. After: FK becomes `null=False`.
- `backend/core/models.py::Conversation` — add the `store` FK field.
- `backend/api/views_admin_stores.py` (new) — `GET /api/admin/stores/` returns the list of stores for the store-switcher.
- `backend/api/views.py`, `backend/api/views_memberships.py`, `backend/api/views_outbound.py`, `backend/api/views_campaigns.py`, `backend/api/views_metrics.py`, `backend/api/views_public.py`, `backend/api/views_qr.py` (or wherever the QR views live) — replace `Store.objects.first()` with `request.store` across all admin endpoints. The single public branding endpoint reads from URL kwarg / fallback (still works for legacy `/api/public/store-brand/` callers because of the fallback).
- `backend/api/webhooks_twilio.py` — each Twilio webhook (sms / whatsapp / voice) sets `conversation.store` at creation. The resolver picks store from `customer.store` (looked up by normalized phone) or falls back.
- `backend/agent/loop.py::AgentLoop.run` — passes `conversation.store` to tool dispatch. Tools that take a store parameter (most do, implicitly via `Resource.store` and `Booking.store`) now have it explicit.
- `backend/agent_tools/tools.py` — `check_availability`, `get_resource_details`, `create_booking`, `modify_booking`, `cancel_booking` accept `store_id` explicitly (today they default to first store).
- `backend/core/management/commands/seed_data.py` — extend with a second store ("PlayDesk North · Toronto") + its resources + its QR actions.

### Infrastructure
- No new pip deps, no new env vars.
- One additive migration + one data migration on `core.Conversation`.

## Implementation Strategy

Sequential, because the swap from implicit-single-store to explicit-request-store can't be partial — half the views looking at request.store and half at Store.objects.first() would cross-leak data inconsistently.

The order:
1. Middleware first — establishes `request.store` everywhere with the safe default. No behaviour change yet.
2. `Conversation.store` migration + backfill — adds the agent-layer plumbing.
3. Backend view sweep — replace `Store.objects.first()` with `request.store` across admin views + agent tools.
4. Frontend StoreContext + StoreSwitcher + admin layout wrap — surfaces the switcher.
5. Customer URL prefix `/s/[slug]/book` + the `/` redirect.
6. Seed second store + e2e isolation test.

After step 1, every existing test still passes (resolver falls back to the single seeded store). After step 3, the existing single-store tests still pass (one store → `request.store` == `Store.objects.first()`). Tests for the new multi-store behaviour land in steps 3 and 6.

## Task Breakdown Preview

- 001 — `CurrentStoreMiddleware` + `request.store` resolver + cookie helper + tests
- 002 — `Conversation.store` FK migration + data backfill + agent loop reads `conversation.store`
- 003 — Backend view sweep: every admin view + agent tool filters by `request.store`; `GET /api/admin/stores/` endpoint
- 004 — `StoreContext` provider + `useCurrentStore` hook + `adminFetch` wrapper; `<StoreSwitcher />` in admin nav; admin pages consume the wrapper
- 005 — Customer-facing `/s/[slug]/book` route + `/` 302 redirect to default store
- 006 — Seed second store ("PlayDesk North") + `multi-location.e2e.ts` cross-store isolation test

## Dependencies

- Hard: `foundation` (in main) — `Store` model.
- Hard: `retention` (in main) — `Customer.store` (for conversation-backfill heuristic).
- Hard: `one-qr` (in main) — `Store.slug` (the URL key).
- Hard: `branded-booking` (in main) — `/api/public/store-brand/` (the new customer-facing route uses it scoped).
- Soft: `multi-channel`, `whatsapp`, `voice-scaffold` (in main) — each webhook learns to set `Conversation.store`.
- Blocks: `customer-portal` (v7).

## Success Criteria (Technical)

- All existing 485-test backend suite passes after middleware lands (#001) — proven by running the suite before any view change.
- After #003: a new cross-store isolation test creates customers/bookings in stores A and B, switches `request.store` mid-test, asserts each store's admin view returns ONLY its own rows.
- After #005: a Playwright e2e booking flow at `/s/playdesk-flagship/book` produces a booking visible in admin while switched to Flagship and INVISIBLE while switched to North.
- Backward compat: `/` 302-redirects to `/s/<default>/book` and the existing booking.e2e.ts journey passes unchanged following the redirect.
- After #002 + #003: an inbound WhatsApp from a North customer triggers the agent to call `check_availability(store_id=<north>)` — verified by a tool-trace assertion in an integration test.
- The seeded second store comes up cleanly via `python manage.py seed_data` with no special flags.

## Estimated Effort

- ~3–4 days for one sequential agent. Critical path: 001 → 002 → 003 → 004 → 005 → 006. No parallel fan-out — each task depends on the previous.

## Tasks Created
- [ ] #158 - CurrentStoreMiddleware + request.store resolver + tests (parallel: false)
- [ ] #159 - Conversation.store FK migration + data backfill + agent loop reads conversation.store (parallel: false, depends on 001)
- [ ] #160 - Backend view sweep: every admin view + agent tool filters by request.store; /api/admin/stores/ (parallel: false, depends on 002)
- [ ] #161 - StoreContext + adminFetch + StoreSwitcher in admin nav (parallel: false, depends on 003)
- [ ] #162 - Customer-facing /s/[slug]/book route + / 302 redirect (parallel: false, depends on 003)
- [ ] #163 - Seed PlayDesk North + multi-location.e2e.ts cross-store isolation test (parallel: false, depends on 004, 005)

Total tasks: 6
Parallel tasks: 0
Sequential tasks: 6
