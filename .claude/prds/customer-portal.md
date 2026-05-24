---
name: customer-portal
description: Self-service customer dashboard at /s/[slug]/account — phone+OTP login, view/reschedule/cancel bookings, see loyalty balance + tier + reward catalogue. Builds on v6 multi-location, v4 memberships, v3 one-qr.
status: backlog
created: 2026-05-24T00:00:00Z
---

# PRD: customer-portal

## Executive Summary

Today every customer interaction with PlayDesk is staff-mediated or agent-mediated: customers book through the kiosk page, scan a QR card to chat with the agent, or call/text and let the agent + staff handle it. There is no logged-in customer surface. A customer who wants to see "my bookings", "my points", or "reschedule next Friday's session" must contact the store.

This epic ships the self-service customer-facing dashboard: `/s/[slug]/account`, gated by phone-number + one-time SMS code, surfacing exactly the four things customers actually ask staff for — upcoming bookings (with reschedule + cancel), booking history, loyalty balance + tier + reward catalogue, and a profile section (name + phone).

It deliberately ships nothing payments-related (that's v9 billing-payments) and nothing pricing-related (v8 pricing-rules). The portal is a *read + control surface* over data that already exists.

## Problem Statement

The product has 4 customer-facing entry points today:

- `/s/[slug]/book` (v6) — anonymous booking flow, drops a `pd_customer` cookie after first booking.
- `/qr/[slug]` (v3 one-qr) — landing page after scanning the in-store QR; resolves customer from cookie, links to chat.
- SMS / WhatsApp / Voice — agent-mediated.
- The agent itself for chat-based questions.

All of these are one-shot or agent-mediated. None lets a returning customer answer "what are my upcoming bookings?" or "how many loyalty points do I have?" without going through staff or the agent. Staff currently handle these requests manually via the admin customer-detail page — a poor use of staff time, and it forces the customer into a synchronous channel (phone, in-person, or waiting for the agent to come back).

The data is all there: `Customer`, `Booking`, `PointTransaction`, `Reward`, `RewardTier` — every row keyed to a store via v6. The portal just needs to surface it behind a customer-friendly auth gate.

## User Stories

- **As a returning customer**, I tap "My Account" on the `/qr/[slug]` landing page, enter my phone, receive a 6-digit SMS code, enter it, and land on my dashboard. The login takes ≤ 60 seconds end-to-end.
  - *Acceptance:* OTP delivered via the existing Twilio SMS adapter; code valid for 10 min; 5-attempt rate limit per phone; session cookie (`pd_customer_session`) lasts 30 days.
- **As a customer**, my dashboard shows upcoming bookings (date, time, resource, status) with a "Reschedule" button and "Cancel" button on each.
  - *Acceptance:* Reschedule opens a date/time picker pre-filtered to the same resource's availability; on submit, updates the booking row + sends a confirmation SMS. Cancel asks for confirmation, sets `status="cancelled"`, sends a confirmation SMS. Both respect the store's cancellation policy field (free up until N hours before).
- **As a customer**, I can see my full booking history (last 50, paginated) — status badges for completed / cancelled / no-show.
- **As a customer**, I see my loyalty card: current point balance, tier name + perks, progress bar to next tier (uses the same payload as v4's MembershipView), and the catalogue of rewards I can redeem (filtered to `cost_points <= balance`).
  - *Acceptance:* Redeem from the portal goes through the existing `/api/admin/customers/{id}/redeem/` endpoint, repurposed (or fronted by a customer-scoped wrapper that enforces `customer == request.customer`).
- **As a customer**, I can edit my display name. Phone is read-only — changing it requires staff (security, since phone is the login).
- **As a customer**, "Log out" clears the session cookie and returns me to `/s/[slug]/book`.
- **As a customer at a chain**, my account at PlayDesk Flagship and my account at PlayDesk North are *separate* — each store has its own Customer rows (per v6 isolation). I see only the store I'm currently on, and switching stores requires logging in again.
  - *Acceptance:* the portal URL is store-scoped (`/s/[slug]/account`); the session cookie includes the store slug so a stolen cookie doesn't cross-leak; if the cookie's store doesn't match the URL slug, force re-login.

## Functional Requirements

1. **Customer OTP auth** — new Django models + endpoints:
   - `core.CustomerOTP(phone, code, expires_at, attempts, created_at)` — TTL 10 min, 5-attempt cap, one valid code per phone at a time (new request invalidates prior).
   - `POST /api/customer-auth/request-code/` body `{phone, store_slug}` → generates 6-digit code, sends via Twilio SMS, returns `{request_id}`. Rate-limited to 1 request per phone per 60 s + 5 per phone per hour.
   - `POST /api/customer-auth/verify-code/` body `{phone, code, store_slug}` → on success, find-or-404 the `Customer` (`phone__exact`, `store__slug__exact`), sign a `pd_customer_session` cookie (signed JWT or Django signed cookie) with `{customer_id, store_id, exp}`, return `{customer: {id, name}}`.
   - `POST /api/customer-auth/logout/` → clears cookie.
   - Customer-scoped middleware `CustomerSessionMiddleware` (separate from staff auth) reads the cookie, sets `request.customer` if valid, else `None`. Verifies `customer.store_id` matches `request.store.id`; mismatch → unset.
2. **Customer-scoped API endpoints** — all return 401 if `request.customer is None`:
   - `GET /api/me/` — `{id, name, phone, store_slug}`.
   - `PATCH /api/me/` — accepts `{name}` only.
   - `GET /api/me/bookings/?status=upcoming|past&limit=N&offset=M` — paginated.
   - `POST /api/me/bookings/{id}/reschedule/` body `{start_at, end_at}` — validates the customer owns the booking, reuses booking-create's overlap check, sends SMS confirmation.
   - `POST /api/me/bookings/{id}/cancel/` — same ownership check, respects cancellation policy (new `Store.cancellation_lead_hours: int` field, default 24; if booking is < N hours away, return 409 with "contact staff").
   - `GET /api/me/membership/` — same payload shape as v4 `MembershipView` (composite: balance + tier + ledger + available rewards).
   - `POST /api/me/redeem/` body `{reward_id}` — fronts the existing redeem logic (ownership + same atomic transaction).
3. **Frontend portal pages** (Next.js App Router, all under `frontend/src/app/s/[slug]/account/`):
   - `page.tsx` — if not logged in, renders the login form; if logged in, renders dashboard.
   - `login/` is *not* a separate route; the login UI is inline (single page so the slug stays in URL). Two-step: phone entry → code entry.
   - Dashboard sections (tabbed or stacked): **Upcoming**, **History**, **Loyalty**, **Profile**.
   - Reuses `frontend/src/lib/store-brand.ts` for header branding (v5 branded-booking).
   - Uses `customerFetch` (a new sibling to v6's `adminFetch`) that automatically sends the session cookie and the store slug header; on 401 → redirect to login.
4. **Wire entry points** — add a "My Account" button to:
   - `/qr/[slug]` landing page (v3) — top-right, next to chat.
   - `/s/[slug]/book` (v6) — top-right header.
   - Both link to `/s/[slug]/account`.
5. **Reschedule + cancel notifications** — both actions emit an outbound SMS via the existing v4 outbound adapter (channel="sms", template="booking_rescheduled" / "booking_cancelled"). Templates live in `core.OutboundTemplate` (existing model).
6. **Cancellation policy field** — `Store.cancellation_lead_hours: PositiveIntegerField(default=24)`. Surfaced in the portal's cancel-confirmation dialog: "Free cancellation up to 24 hours before".
7. **Customer profile completeness check** — if `customer.name` is empty on first login (anonymous booking + cookie-only history), force a one-time "what should we call you?" step before showing the dashboard.

## Non-Functional Requirements

- **Session security**: cookie is `HttpOnly`, `Secure`, `SameSite=Lax`; signed with `SECRET_KEY`; includes store_id binding so a stolen cookie can't cross-leak; 30-day TTL.
- **Rate limiting** on OTP request (1/60s, 5/hour per phone); OTP verify (5 attempts per code, then invalidate); login attempts logged to a new `CustomerLoginAttempt` table for staff audit.
- **No PII leakage**: portal endpoints never return phone in any list view (only in `/api/me/`); never return another customer's data.
- **Mobile-first**: dashboard renders cleanly at 375×667 (iPhone SE). Most customers will arrive via `/qr/[slug]`, which is a mobile-only flow.
- **Backward compat**: nothing breaks. The 9 existing customer-facing routes (`/`, `/s/[slug]/book`, `/qr/[slug]`, etc.) keep working. No staff-side change required.

## Dependencies

- **v6 multi-location** (shipped) — store-context resolver, store-scoped customer URLs, `customerFetch` pattern.
- **v4 memberships** (shipped) — composite payload for loyalty section, redeem atomic logic.
- **v4 outbound** (shipped) — SMS adapter for OTP delivery + reschedule/cancel notifications.
- **v3 one-qr** (shipped) — `pd_customer` cookie semantics; "My Account" entry point.

## Out of Scope

- Account creation outside the booking flow (customers are still created at first booking).
- Password auth (phone+OTP only).
- F&B ordering, in-store check-in flow, loyalty card sharing.
- Payments — entirely v9 billing-payments. Reschedule does *not* re-collect any deposit in this slice.
- Pricing breakdown display — entirely v8 pricing-rules. Bookings show `total_amount` as a single number.
- Email channel — v6 is SMS-only for both OTP and notifications.
- Multi-store account linking ("see my bookings across all PlayDesk locations"). Each store-customer is independent in v7.

## Expected Conflict Zones with Peer Epics (v8, v9)

- `Booking` model: v9 will add `payment_status`, `payment_intent_id`. Portal serializers ignore these unless present.
- `OutboundTemplate`: v7 adds `booking_rescheduled` + `booking_cancelled`. v9 will add `payment_*` templates. Different rows, no conflict.
- `frontend/src/lib/customer-fetch.ts`: v7 creates it. v8/v9 won't touch.
- Migration ordering: v7 adds `CustomerOTP` + `CustomerLoginAttempt` + `Store.cancellation_lead_hours`. v8 adds pricing tables. v9 adds payment tables. All additive — merge migration if numbers collide.
