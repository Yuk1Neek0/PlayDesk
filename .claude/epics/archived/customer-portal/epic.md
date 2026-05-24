---
name: customer-portal
status: completed
created: 2026-05-24T04:00:00Z
updated: 2026-05-24T11:50:00Z
progress: 100%
prd: .claude/prds/customer-portal.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/165
---

# Epic: customer-portal

## Overview

A self-service customer dashboard at `/s/[slug]/account`. Customer auth via phone + 6-digit SMS OTP (Twilio via the existing v4 outbound adapter). After login, four tabs: Upcoming (reschedule + cancel), History, Loyalty (uses v4's MembershipView payload + redeem), Profile (name only, phone read-only). One new middleware (`CustomerSessionMiddleware`), one new auth-cookie scheme, ~6 new `/api/me/*` endpoints, one new Next.js route segment, plus "My Account" entry-point wiring on `/qr/[slug]` and `/s/[slug]/book`.

## Architecture Decisions

- **OTP, not password.** PlayDesk customers are identified by phone number from day one (booking flow, agent channels, QR cookie). Adding password auth would mean a new credential to forget; OTP via the channel they already trust is the simplest secure flow. Mirrors how every consumer ride/food app onboards in this region.
- **Customer session is a separate middleware from staff auth, not a unified user model.** `Customer` is not a Django `User`. Two reasons: (a) staff and customer auth lifecycles are completely different (staff = Django admin, customer = SMS), (b) accidental privilege confusion is the worst-case bug — keeping the two namespaces strictly separate eliminates it.
- **Signed cookie with store binding, not JWT.** Django's signed cookies are simpler than JWTs and the payload is small (customer_id + store_id + exp). Store binding in the cookie payload means a stolen cookie can't cross-leak across the customer's accounts at different stores.
- **Reuse v4's membership endpoints under `/api/me/*` instead of writing parallel ones.** The composite payload is already perfectly shaped for the loyalty tab. Reuse means the v4 logic stays the single source of truth — bug fixes in one apply to both surfaces.
- **Phone is read-only in the portal.** Changing the login identifier needs staff verification (anti-takeover). v7 ships this as a hard constraint; v8+ can add a phone-change ceremony.
- **No email channel in v7.** OTP, reschedule, cancel — all SMS via v4 outbound. Email is added in v9 (billing receipts need it more).

## Technical Approach

### Frontend Components
- `frontend/src/app/s/[slug]/account/page.tsx` (new) — server component, reads session cookie. If valid → dashboard shell; else → login form.
- `frontend/src/app/s/[slug]/account/AccountDashboard.tsx` (new) — client component with 4 tabs: Upcoming, History, Loyalty, Profile.
- `frontend/src/app/s/[slug]/account/LoginForm.tsx` (new) — two-step: phone → code.
- `frontend/src/lib/customer-fetch.ts` (new) — sibling of v6's `adminFetch`. Auto-sends cookie + store slug header; on 401 → redirects to login.
- `frontend/src/app/qr/[slug]/page.tsx` — add "My Account" button.
- `frontend/src/app/s/[slug]/book/BookingPage.tsx` — add "My Account" header link.

### Backend Services
- `backend/core/models.py` — add `CustomerOTP`, `CustomerLoginAttempt`; add `Store.cancellation_lead_hours` (default 24).
- `backend/core/middleware.py::CustomerSessionMiddleware` (new) — reads `pd_customer_session` cookie, validates signature, sets `request.customer`. Mismatched store_id → unset.
- `backend/api/views_customer_auth.py` (new) — request-code, verify-code, logout endpoints + rate-limit decorator.
- `backend/api/views_me.py` (new) — `/api/me/`, `/api/me/bookings/`, reschedule, cancel, `/api/me/membership/` (delegates to v4's MembershipView), `/api/me/redeem/` (delegates to v4's RedeemView).
- `backend/core/outbound_templates.py` (or wherever templates live) — add `customer_otp`, `booking_rescheduled`, `booking_cancelled`.
- `backend/config/settings.py` — register middleware after `CurrentStoreMiddleware`.

### Infrastructure
- No new pip deps (Django signed-cookie is built-in).
- One additive migration (`CustomerOTP`, `CustomerLoginAttempt`, `Store.cancellation_lead_hours`).

## Implementation Strategy

Mostly parallelizable internally:
- 166 (auth backend) must land first — middleware + endpoints + models.
- 167 (me endpoints) depends on 166's middleware.
- 168 (membership/redeem delegation) depends on 166.
- 169 (frontend dashboard + login) depends on 166's API contract — can start in parallel using mocked responses.
- 170 (entry-point wiring) can start any time after 169 lands the route.
- 171 (e2e test) last.

One agent runs the epic sequentially. Estimated wall-time: 30–60 min for the agent.

## Task Breakdown Preview

- 166 — `CustomerOTP` + `CustomerLoginAttempt` models + auth endpoints + `CustomerSessionMiddleware` + rate limiting + SMS OTP delivery via v4 outbound
- 167 — `/api/me/*` endpoints (profile, bookings list, reschedule, cancel) + `Store.cancellation_lead_hours` + reschedule/cancel SMS notifications
- 168 — `/api/me/membership/` + `/api/me/redeem/` delegating to v4 logic + ownership checks
- 169 — Frontend `/s/[slug]/account/` page + dashboard 4-tab shell + login flow + `customerFetch` wrapper
- 170 — "My Account" entry-point wiring on `/qr/[slug]` and `/s/[slug]/book`
- 171 — `customer-portal.e2e.ts`: login → reschedule → cancel → redeem reward

## Dependencies

- Hard: `multi-location` (v6, in main) — store-scoped customer URLs, `customerFetch` precedent.
- Hard: `memberships` (v4, in main) — `MembershipView`, `RedeemView`, atomic redeem logic.
- Hard: `outbound` (v4, in main) — Twilio SMS adapter for OTP + reschedule/cancel notifications.
- Hard: `one-qr` (v3, in main) — `/qr/[slug]` landing page for "My Account" entry point.
- Soft: `branded-booking` (v5, in main) — portal header reuses brand fetch.

## Success Criteria (Technical)

- Existing backend test suite passes after middleware lands.
- New tests in `tests/test_customer_auth.py`: rate limits, code expiry, store binding, attempt cap.
- New tests in `tests/test_me_endpoints.py`: ownership enforcement, cancellation lead-hours, reschedule overlap check.
- `customer-portal.e2e.ts` happy-path: phone entry → code entry → land on dashboard → see upcoming booking → cancel → confirmation SMS template-rendered.
- Stolen-cookie test: cookie from Flagship sent to North's account URL → forced re-login, no data leak.

## Estimated Effort

- Single agent, sequential within the epic. ~30–60 min wall-time.

## Tasks Created
- [ ] #166 - CustomerOTP/LoginAttempt models + auth endpoints + CustomerSessionMiddleware + SMS OTP delivery (parallel: false)
- [ ] #167 - /api/me/ profile + bookings + reschedule + cancel + cancellation_lead_hours + SMS notifications (parallel: false, depends on 166)
- [ ] #168 - /api/me/membership + /api/me/redeem delegating to v4 (parallel: true, depends on 166)
- [ ] #169 - Frontend /s/[slug]/account/ + dashboard + login + customerFetch (parallel: true, depends on 166)
- [ ] #170 - My Account entry-point wiring on /qr/[slug] + /s/[slug]/book (parallel: true, depends on 169)
- [ ] #171 - customer-portal.e2e.ts (parallel: false, depends on 167, 168, 169, 170)

Total tasks: 6
