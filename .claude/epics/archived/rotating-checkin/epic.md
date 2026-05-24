---
name: rotating-checkin
status: completed
created: 2026-05-24T15:30:00Z
updated: 2026-05-24T16:05:00Z
progress: 100%
prd: .claude/prds/rotating-checkin.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/203
---

# Epic: rotating-checkin

## Overview

In-store rotating QR for walk-ins + customers who lost/can't access their booking SMS. A single QR display (tablet or print) at the door rotates its encoded key every 15 minutes; scanning lands the customer on `/c-in/?k=<key>` which asks for phone, sends an SMS OTP (reusing v7's `CustomerOTP`), verifies, then queries bookings within a same-day ±2hr window. Coexists with v10b's per-booking SMS-link flow — both paths reach the same `BookingStatus.CHECKED_IN` end state.

## Architecture Decisions

- **DB-backed rotating keys, not stateless JWT.** Cheap to audit ("show me the key sequence for last hour"), trivially invalidated (delete row), and the `superseded_at` grace window is easier with rows. JWTs would mean a server-side denylist anyway for invalidation, which is what we just avoided.
- **Cron-driven rotation, not a service.** `rotate_checkin_keys` management command runs every minute via cron; for each store, if the most-recent key is older than its `checkin_rotation_minutes`, mint a new one. If cron breaks, the previous key keeps working until its `expires_at` — 60s grace prevents a wave of "code expired" errors mid-scan.
- **100% v7 OTP infra reuse.** Don't add `RotatingCheckinOTP` or similar — `CustomerOTP` already exists with rate limits, expiry, attempt cap. v11a's `/api/c-in/request-otp/` is a thin wrapper that calls v7's `request_code`.
- **Same-day ±2hr lookup window is the trust gate.** Even if both rotating key + OTP were somehow bypassed, an attacker still couldn't check in tomorrow's bookings. Defense in depth.
- **Walk-in self-registration deferred.** Zero matches → "see staff" message. Building a self-service walk-in flow means new Customer + Booking creation from this surface, which is a v12 epic.
- **Phone is the only identity.** No per-customer cookies / portal sessions involved. Anyone with the right phone + receives the OTP can check in. Matches the v10b SMS-link trust model.

## Technical Approach

### Backend Services
- `backend/checkin/` (new Django app) — `models.py` (`RotatingCheckinKey`), `services.py` (`get_active_key`, `mint_key`), `views.py` (4 public endpoints), `management/commands/rotate_checkin_keys.py`.
- `backend/core/models.py::Store` — add `checkin_rotation_minutes: PositiveSmallIntegerField(default=15)`.
- Migrations: `checkin/migrations/0001_initial.py` + `core/migrations/000X_store_checkin_rotation.py`.
- URL wiring: `path("c-in/", include("checkin.urls"))` under the `/api/` prefix in `backend/config/urls.py`.

### Frontend Components
- `frontend/src/app/c-in/page.tsx` (new) — server component reads `?k=<key>`, server-fetches `/api/c-in/lookup-key/`. On 410, render expired-state card; else render `<RotatingCheckinClient />`.
- `frontend/src/app/c-in/RotatingCheckinClient.tsx` (new) — multi-step state machine: phone → OTP → match resolution (0/1/many) → confirmation.
- `frontend/src/app/admin/settings/checkin/page.tsx` (new) — current key display + rotation period editor + "Show fullscreen" button + "Rotate now" action.
- `frontend/src/app/admin/settings/checkin/display/page.tsx` (new) — fullscreen QR for the lobby tablet, auto-refreshes every `rotation_minutes / 2` seconds.

### Infrastructure
- No new pip / npm deps. QR rendering on the frontend uses a tiny client-side lib OR a `<img>` to a `/api/c-in/qr.png` server-rendered endpoint. Pick whichever is simpler at implementation time.
- 2 additive migrations.

## Implementation Strategy

Mostly sequential within the epic — each step depends on the prior schema/endpoint:

1. **#204 Schema + rotation command** — model + Store field + rotate command + tests.
2. **#205 Public endpoints** — 4 endpoints, OTP reuse, the match-finding logic.
3. **#206 Public frontend** — `/c-in/` page + multi-step client.
4. **#207 Admin settings** — display + rotate-now + fullscreen.
5. **#208 Tests** — e2e covering happy path + expired key + multi-booking disambiguation + walk-in dead end.

Single agent, ~45-60 min wall-time.

## Task Breakdown Preview

- 204 — `RotatingCheckinKey` model + `Store.checkin_rotation_minutes` + migrations + `rotate_checkin_keys` management command + tests
- 205 — Public `/api/c-in/{lookup-key,request-otp,verify-and-find,check-in}/` endpoints (reuses v7 CustomerOTP)
- 206 — Frontend `/c-in/?k=` page + multi-step flow (phone → OTP → matches → confirmation)
- 207 — Admin `/admin/settings/checkin/` page + fullscreen display + manual rotate-now button
- 208 — Tests: backend unit + frontend unit + `rotating-checkin.e2e.ts`

## Dependencies

- Hard: `multi-location` (v6, in main) — `request.store`, store-scoped URLs.
- Hard: `customer-portal` (v7, in main) — `CustomerOTP` model + `request_code` / `verify_code` flow. **Pure reuse, no fork.**
- Hard: `checkin` (v10b, in main) — `BookingStatus.CHECKED_IN`, `checked_in_at`, the check-in flip pattern.
- Hard: `outbound` (v4, in main) — SMS adapter for OTP delivery.

## Success Criteria (Technical)

- Existing 739-test backend suite passes after migration.
- New tests in `checkin/tests/`: key rotation logic (mint new when older than interval), `superseded_at` grace window, key-not-found 410, OTP reuse path.
- e2e `rotating-checkin.e2e.ts`:
   1. Scan QR with valid key → land on phone entry.
   2. Wrong OTP → friendly retry.
   3. Correct OTP + 1 match → "✓ Checked in" + admin booking list shows the badge.
   4. Correct OTP + 0 matches → walk-in message.
   5. Scan an expired key → "ask staff" card.

## Estimated Effort

- Single agent, ~45-60 min wall-time.

## Tasks Created
- [ ] #204 - RotatingCheckinKey model + Store.checkin_rotation_minutes + rotate_checkin_keys command (parallel: false)
- [ ] #205 - Public /api/c-in/ endpoints (lookup-key, request-otp, verify-and-find, check-in) (parallel: false, depends on 204)
- [ ] #206 - Frontend /c-in/?k= page + multi-step flow (parallel: false, depends on 205)
- [ ] #207 - Admin /admin/settings/checkin/ page + fullscreen display + rotate-now (parallel: false, depends on 205)
- [ ] #208 - Tests: backend + frontend + rotating-checkin.e2e.ts (parallel: false, depends on 206, 207)

Total tasks: 5
