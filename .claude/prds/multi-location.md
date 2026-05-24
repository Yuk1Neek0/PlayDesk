---
name: multi-location
description: Surface the per-store data layer that's existed since v1 — add a current-store context resolver, an admin store-switcher, store-scoped URLs for the booking flow, and Conversation.store so the agent knows which store it's serving.
status: backlog
created: 2026-05-24T02:12:13Z
---

# PRD: multi-location

## Executive Summary

PlayDesk's data layer has supported multiple stores since v1 — every booking, customer, resource, QR action, outbound message, campaign, and reward is already keyed by a `store_id` FK. But every read path assumes `Store.objects.first()`. The admin nav says "DOWNTOWN · TORONTO" as a hardcoded string; the booking page knows about one store; the agent's `check_availability` tool scopes nothing. Adding a second store today produces invisible data.

This epic surfaces that data layer: a request-level `current_store` resolver (middleware + cookie + URL slug), an admin store-switcher chip in the nav, store-scoped customer URLs (`/s/[slug]/book`), a `Conversation.store` FK so the agent knows which store it's serving on any channel, and a seeded second store so the surface has something to demonstrate. Closes the "multi-location support" item on the COSReady-website feature list, and unblocks v7's customer-facing portal (which needs store-context from day one).

## Problem Statement

The single-store assumption is baked into the read paths but not the write paths:

- **Hardcoded in the frontend**: the admin nav header literally says "DOWNTOWN · TORONTO"; the booking page logo + name come from a single SSR call to `/api/public/store-brand/` that returns the default store.
- **Hardcoded in the backend**: every admin view (`AdminBookingListView`, `AdminCustomerListView`, etc.) returns rows across ALL stores (because there's only one); the public booking endpoint always uses `Store.objects.first()`; the agent's tools query without store filtering.
- **Invisible in the data**: `Conversation` has no `store` FK — when the agent answers an SMS at hypothetical store B, the agent has no idea which store the customer is asking about, and `check_availability` would return store A's resources too.

So even though a store-chain owner can create a "PlayDesk North" row in Django admin today, nothing in the product reflects it: bookings cross-leak in lists, the agent gives mixed answers, the admin dashboard sums irrelevantly across both, and the customer can only book at one store via the booking page.

Multi-location is also blocking v7 (customer-facing portal), which must be store-aware: a customer logging in to see "their bookings" needs the system to know which store they're a customer of.

## User Stories

- **As a store-chain owner**, I can click between "PlayDesk Downtown" and "PlayDesk North" in the admin nav and watch the bookings list, customers list, dashboard metrics, outbound log, and campaigns refresh to show only that store's data.
  - *Acceptance:* selecting a store sets a cookie; every admin page re-fetches scoped to the selected store; the selection persists across sessions.
- **As a customer**, scanning the QR card at the North location lands me on the North-branded landing page; tapping "book a session" lands me on `/s/playdesk-north/book` with North's resources and North's branded header; the booking I make is linked to North.
  - *Acceptance:* `/qr/playdesk-north` already works (v3); `/s/playdesk-north/book` is new in this slice; the booking flow respects the URL store from end to end.
- **As a customer**, when I SMS or WhatsApp the store, the agent answers using THIS store's resources and policies — not the other location's.
  - *Acceptance:* `Conversation.store` is set at conversation-creation time; the agent loop reads it; `check_availability` / `get_resource_details` filter by it.
- **As a developer**, adding a new store via Django admin requires zero code changes — it shows up in the selector, gets its own URLs, has its own admin scope, and is immediately operable.
  - *Acceptance:* the seeded "PlayDesk North" store comes from a single `Store.objects.create(...)` call in `seed_data.py` plus standard FK seeds for resources; no special code path.
- **As a chain manager**, the existing single-store URLs (`/`, `/qr/[slug]`, the old admin pages without a store cookie) keep working by defaulting to the alphabetically-first store — no broken links during the migration.

## Functional Requirements

1. **Current-store resolver** — Django middleware at `backend/core/middleware.py::CurrentStoreMiddleware`:
   - Sets `request.store` (a `Store` instance) on every request.
   - Resolution order (first hit wins):
     1. URL kwarg `store_slug` (set by the customer-facing `/s/[slug]/...` URL prefix).
     2. `X-PD-Store-Slug` request header (admin frontend sets this from its `StoreContext`).
     3. `pd_store_slug` cookie (admin selector persists here).
     4. Fallback: alphabetically-first `Store` (so legacy single-store URLs keep working).
   - Sets the cookie when the header is present (so cross-tab navigation keeps the same store).
2. **`Conversation.store` FK** — additive migration on `core.Conversation`. Backfill from existing data:
   - SMS, WhatsApp, voice rows where `customer_identifier` matches a `Customer.phone` → use that customer's store.
   - Web-chat rows: backfill to `Store.objects.first()` (the only store that existed historically).
   - Field becomes required for new rows after the backfill.
3. **Conversation-create paths set `store` explicitly**:
   - Inbound SMS / WhatsApp / Voice webhooks: from `request.store` (which the resolver populates from the customer's phone-lookup or falls back to default).
   - Web-chat `POST /api/conversations/`: pulls `store` from `request.store` (resolver reads the X-PD-Store-Slug header or cookie).
4. **Agent loop reads `conversation.store`**:
   - `AgentLoop.run(conversation, ...)` passes `conversation.store` to tool calls.
   - Tools that have to be store-scoped: `check_availability`, `get_resource_details`, `create_booking`, `modify_booking`, `cancel_booking`, `search_knowledge_base` (if KB chunks gain a store FK later — out of scope for v6, RAG stays global).
5. **All admin views filter by `request.store`**:
   - `AdminConversationListView`, `AdminBookingListView`, `AdminCustomerListView`, `AdminCustomerDetailView` (404 if customer is from a different store), QR endpoints, Outbound, Campaigns, Memberships (rewards/tiers/membership view), business-metrics dashboard.
   - Anywhere that currently does `Store.objects.first()` becomes `request.store`.
6. **Admin store-switcher** — chip group in the admin nav header (`frontend/src/components/admin/store-switcher.tsx`):
   - Lists all stores from `GET /api/admin/stores/` (new endpoint — returns id, slug, name for stores the staff user can access; v6 = all stores).
   - Click switches the current store: sets `pd_store_slug` cookie + updates `StoreContext` (new React context that wraps the admin layout).
   - The currently-selected store's name replaces the hardcoded "DOWNTOWN · TORONTO" string in the nav.
   - Selection persists in localStorage (so the next visit opens to the same store).
7. **Admin frontend respects current store** — every admin page's data fetches include `X-PD-Store-Slug: <current>` (via a small `adminFetch` wrapper that reads from `StoreContext`).
8. **Customer-facing URL prefix** — new Next.js route `frontend/src/app/s/[slug]/book/page.tsx` mirrors the current `app/page.tsx`. The slug is the `Store.slug`. The page passes `?store=<slug>` to the availability + booking-create API calls.
9. **Backward-compat redirects** — `/` redirects to `/s/<default-store-slug>/book` (302), so existing bookmarks / QR-card prints keep working. The redirect's target is the alphabetically-first store (matches the resolver's fallback).
10. **`/api/admin/stores/` endpoint** — `GET` returns `[{id, slug, name}]` for all stores (v6 doesn't have per-staff store-membership ACL; v7 will).
11. **Seed second store** — extend `seed_data.py` to create "PlayDesk North · Toronto" with its own resources (2 PS5 stations, 1 room), its own QR actions (default set), and its own brand metadata. Slug: `playdesk-north`. Existing demo store gets the slug `playdesk-flagship` (already does).

## Non-Functional Requirements

- **Backward compatibility**: `/` and `/qr/[slug]` keep working (the latter is already store-scoped; the former 302-redirects). No 404s for any URL that existed before this slice.
- **One additive migration** for `Conversation.store` + one data migration for the backfill. No destructive schema changes.
- **All existing tests pass** after this slice. Tests that implicitly assumed a single store (most of them — they create one store in fixtures and don't assert on cross-store leakage) continue to work because:
   - The middleware defaults to the alphabetically-first store when no resolver hit.
   - Test fixtures create one store, so the fallback resolves correctly.
- **Per-store isolation is provable** — at least one new test creates customers/bookings in TWO stores and asserts that an admin view scoped to store A returns zero rows from store B.
- **No regression in agent behaviour for single-store deployments** — a deployment with only one store keeps acting exactly as it does today.
- **The store-switcher must work without a page reload** — switching stores triggers an in-place re-fetch of every visible data section (admin pages already poll/refetch on their own; the new fetch wrapper reads the current cookie value at fetch time, not mount time).
- **Cookie + localStorage stay in sync** — the `StoreContext` provider writes both on switch; the middleware reads only the cookie.

## Success Criteria

- A reviewer can: create "PlayDesk North" via the seeded second store, switch to it in the admin nav, see zero bookings (because it's empty), book a session at `/s/playdesk-north/book`, see the booking appear ONLY in the North admin view, switch back to Flagship and see ZERO North bookings.
- Sending a WhatsApp message from a phone associated with a North-store customer triggers the agent to use North's resources for `check_availability`.
- The existing 485-test backend suite passes; ≥10 new tests cover the resolver, the cross-store isolation invariant, the URL-prefix routing, and the conversation-store backfill.
- The existing Playwright e2e suite passes; a new `multi-location.e2e.ts` test switches stores in the admin nav and verifies the booking-list re-fetches.
- Lighthouse score on `/s/playdesk-flagship/book` does not regress from today's `/`.

## Constraints & Assumptions

- **Per-staff store-membership ACL is OUT OF SCOPE** for v6. Any staff user can switch to any store. v7 will add `StaffStore` join table + filter the `GET /api/admin/stores/` endpoint by it.
- **No subdomain-based routing** — URL path prefix only (`/s/[slug]/...`). Subdomains add DNS + Cert work that's not justified yet.
- **"All Stores" aggregate view is OUT OF SCOPE for v6** — single-store-at-a-time only. Cross-store roll-up dashboards are a v7+ concern.
- **RAG chunks (KnowledgeBase) stay global in v6** — `search_knowledge_base` returns chunks regardless of store. If a chain wants per-store KB, that's a follow-on (would need a `KnowledgeChunk.store` FK + migration).
- **Per-store agent system-prompt customization is out of scope.** Same prompt for all stores in v6.
- **The default store is the alphabetically-first one** — not configurable in v6. (Configurable "primary store" would be UI-driven; out of scope.)

## Out of Scope

- Per-staff store-membership ACL (`StaffStore` model). → v7.
- Cross-store reporting / chain-wide aggregations. → v7+.
- Subdomain-based multi-tenancy (`flagship.playdesk.app`).
- Per-store agent prompt customization.
- Per-store KB (RAG chunks scoped to a single store).
- Customer self-serve store switching beyond URL slug.
- Multi-tenant DB-level isolation (still one Postgres, one schema, FK enforces per-store rows).
- A "create new store" UI in admin — store creation stays a Django-admin / fixtures concern.
- Migrating customer-facing email/SMS templates per store. (Templates stay global; only the rendered store name varies.)

## Dependencies

- Hard: `foundation` (in main) — `Store` model, `Resource.store` FK, all the per-store FK plumbing.
- Hard: `retention` (in main) — `Customer.store` for the conversation-backfill heuristic.
- Hard: `one-qr` (in main) — `Store.slug` field + the `/qr/[slug]` URL pattern (the URL convention this slice generalises).
- Hard: `branded-booking` (in main) — `/api/public/store-brand/` already exists; the new `/s/[slug]/book` route uses it scoped to the URL store.
- Soft: `multi-channel` + `whatsapp` + `voice-scaffold` (in main) — each adapter's webhook learns to set `Conversation.store` from the lookup.
- Blocks: `customer-portal` (v7) — needs store-context from day one to know which store a customer "belongs to."
