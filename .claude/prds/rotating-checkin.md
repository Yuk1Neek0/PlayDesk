---
name: rotating-checkin
description: In-store rotating QR for walk-ins + customers who lost their booking SMS. A single QR displayed at the door encodes a short-lived (15 min) rotating key; scanning lands the customer on a public page that asks for their phone, sends an SMS OTP, verifies, then either auto-checks them in (1 same-day booking found) or disambiguates (2+) or surfaces a walk-in pathway (0). Coexists with v10b's per-booking SMS-link flow.
status: backlog
created: 2026-05-24T15:30:00Z
---

# PRD: rotating-checkin

## Executive Summary

v10b shipped per-booking SMS-link check-in: customer arrives, taps the link in their confirmation SMS, status flips. Works perfectly for everyone who shows up with their phone. **Fails for walk-ins, customers whose SMS got buried, and customers whose phone died on the way over.**

This epic adds a complementary path: a single QR displayed at the door (tablet, printout, kiosk — store's choice) that rotates its encoded key every 15 minutes. Scanning lands the customer on `/c-in/?k=<key>`, which asks for their phone, fires a v7-style OTP for identity confirmation, then queries the booking table within a same-day ±2hr window. One match → auto check-in. Multiple → disambiguation. Zero → walk-in registration path (out of scope for this slice; just surfaces a "see staff" message).

The rotating key + OTP + time-window combination together close three attack vectors at once:
- Photo of yesterday's QR is useless (key rotated).
- Stranger with someone else's phone number can't check them in (no OTP).
- Stale check-ins for next week's booking are impossible (time-window).

## Problem Statement

The check-in surface today has three gaps:

1. **Walk-ins are invisible.** A customer who walks in without a booking has no self-service path — staff must manually create + check-in. Common during slow periods when staff are mid-game-setup.
2. **Lost-SMS friction.** Older customers + customers on monthly plans frequently misplace the booking confirmation. Staff currently spend ~30s per customer doing a manual phone-lookup at the door on Friday/Saturday nights.
3. **Dead-phone arrivals.** A customer who shows up but their phone died in transit can't scan their SMS link. Staff workaround: ask for their name, manually look up the booking. Same friction.

The architectural fit is a single in-store QR — the cheapest possible hardware (paper or a $50 tablet). The key insight: the QR doesn't need to encode the customer or booking, just a rolling "this scan is from inside the store right now" token. The customer's identity comes from their phone number; their booking is whichever one their phone has within a small time window.

The rolling-key design is what makes this safe to print. A static QR taped to the door would let anyone with a photo check anyone else in from across town; the 15-min rolling key makes that worthless.

## User Stories

- **As a walk-in customer**, I see the QR at the door, scan, enter my phone, get an OTP via SMS, type it in, and see "No bookings on your phone today — please see staff to register a walk-in session". I'm directed to staff with my phone already on file.
- **As a forgetful customer** with a confirmed booking, I scan the door QR, enter my phone, OTP, see "Welcome back, Alice! Found 1 booking: PS5 Station 2 at 7:00 PM. Tap to check in", tap, get "✓ Checked in".
- **As a customer who booked for two people** (under one phone but two consecutive slots), I scan, OTP, see "Found 2 bookings starting in the next hour: PS5 #2 at 7:00 PM, PS5 #3 at 7:00 PM" — I check each in individually.
- **As staff at a chain store**, I open `/admin/settings/checkin/` to see the currently-active rotating key, the timestamp of its last rotation, and a "Show in big" button that opens a full-screen QR display optimized for a tablet at the door.
- **As an operations manager**, I can configure the rotation period per-store (default 15 min). Stores with low walk-up volume can rotate hourly; high-volume can rotate every 5 min.
- **As an attacker** who photographed the QR yesterday, my scan returns "This code expired — please ask staff for the current QR". I cannot impersonate the store.
- **As an attacker** who guessed a real customer's phone number, my OTP submission fails (the code goes to the customer's phone, not mine). I cannot check anyone in.

## Functional Requirements

1. **`RotatingCheckinKey` model** (`backend/checkin/models.py` — new app `checkin` OR extend `core`):
   - `store` (FK Store).
   - `key`: short URL-safe base32 string (10 chars, ~50 bits entropy).
   - `created_at: DateTimeField(auto_now_add=True)`.
   - `expires_at: DateTimeField` (15 min from creation by default).
   - `superseded_at: DateTimeField(null=True)` — set when the next key replaces this one (so the previous key has a 60-second grace window).
   - Index on `(store, expires_at)`.
2. **`Store` augmentation** — `checkin_rotation_minutes: PositiveSmallIntegerField(default=15)`.
3. **Key management**:
   - `python manage.py rotate_checkin_keys` — for each store, if the most recent key is older than its store's rotation interval, create a new key. The previous key's `superseded_at = now()`. Run via cron every minute (cheap, idempotent).
   - `checkin.get_active_key(store) -> RotatingCheckinKey` — returns the current key (most recent, non-expired). Helper for admin display + UI rendering.
4. **Public endpoints** under `/api/c-in/`:
   - `POST /api/c-in/lookup-key/` body `{key}` → 200 `{store_slug, store_name, expires_at}` if key valid; 410 `{detail: "Code expired — please ask staff for the current QR."}` if expired or unknown.
   - `POST /api/c-in/request-otp/` body `{key, phone}` → validates key + phone format, calls v7's `request_code` flow (`CustomerOTP` model reused) with channel `sms`. Returns `{request_id}`. Rate-limited 1 per 60s, 5 per hour per phone (v7's existing limits).
   - `POST /api/c-in/verify-and-find/` body `{key, phone, code}` → verifies OTP. On success, queries:
     ```python
     window_start = now() - timedelta(hours=2)
     window_end = now() + timedelta(hours=2)
     Booking.objects.filter(
         resource__store=store,
         customer_phone=phone_normalized,
         status=BookingStatus.CONFIRMED,
         start_time__gte=window_start,
         start_time__lte=window_end,
     )
     ```
     Returns `{bookings: [{id, resource_name, start_time, end_time, can_check_in}, ...]}`. Empty list = walk-in path. One = ready-to-check-in. Multiple = disambiguation.
   - `POST /api/c-in/check-in/` body `{key, phone, code, booking_id}` → re-verifies OTP (single-use), checks the booking belongs to phone+store+window, flips to `CHECKED_IN`. Returns the booking payload.
5. **Public frontend** under `/c-in/`:
   - `frontend/src/app/c-in/page.tsx` — reads `?k=<key>` query, server-fetches `lookup-key`. On 410, render expired-state card; else render `<RotatingCheckinClient />`.
   - `RotatingCheckinClient.tsx` — multi-step UI:
     1. **Phone entry**: phone input + Continue → `request-otp`.
     2. **OTP entry**: 6-digit input + Verify → `verify-and-find`.
     3. **Match resolution**: switch on response (0/1/many bookings) → render appropriate card.
     4. **Confirmation**: ✓ Welcome state, mirrors v10b's `/c/[token]/` confirmation panel.
6. **Admin settings page** `/admin/settings/checkin/`:
   - Shows the current active key (truncated for the page; full key visible behind a "reveal" button).
   - Big "Display QR fullscreen" button → opens `/admin/settings/checkin/display` which renders just a giant QR + the next rotation countdown. Designed for a wall-mounted tablet.
   - Editable `checkin_rotation_minutes` field.
   - Manual "Rotate now" button (calls `rotate_checkin_keys --force --store=<slug>`).
7. **Walk-in path** (out of scope as a *flow*, in scope as a *visible affordance*): when `verify-and-find` returns zero matches, the frontend renders "No booking found on this phone today — please see staff to register a walk-in." Staff handle from there. A real walk-in self-registration flow is a v12 candidate.

## Non-Functional Requirements

- **Key entropy**: 10 chars base32 (no ambiguous) = 50 bits. Plus 15-min TTL. Brute force from outside is not possible within the window.
- **OTP infra reuse**: 100% reuse of v7's `CustomerOTP` + `request_code` / `verify_code` flow. Don't duplicate.
- **Rate limits**: same as v7 (1 OTP per phone per 60s, 5 per hour). The lookup-key endpoint is rate-limited per IP (cheap, prevents scanning).
- **No PII in the response payload** until OTP is verified. The lookup-key response is store-name-only (the QR is already at the store; this doesn't leak anything).
- **Backward compat**: v10b's per-booking SMS-link flow is untouched. Both coexist.
- **Mobile-first**: the customer's phone is the only client.

## Dependencies

- v6 multi-location (in main) — `request.store`, store-scoped routes.
- v7 customer-portal (in main) — `CustomerOTP` model + request/verify endpoints (reuse, do not duplicate).
- v10b checkin (in main) — `BookingStatus.CHECKED_IN`, `checked_in_at`, the `/api/admin/bookings/<pk>/check-in/` admin endpoint pattern.
- v4 outbound (in main) — SMS adapter for OTP delivery.

## Out of Scope

- Walk-in self-registration (creating a new Customer + Booking from the c-in flow). Staff path only in v11a; full self-service is a future epic.
- Per-resource QR stickers ("scan the QR taped to PS5 #3 to start a session"). Different model entirely.
- Geofencing / location verification. Privacy + reliability cost not worth it.
- Customer-tier-based shortcuts (e.g. Gold tier skips OTP). All customers get the same flow.
- Display-tablet management as a first-class admin resource (PIN-protected display? Auto-refresh schedule?). Manual refresh is fine.

## Expected Conflict Zones with Peer Epic (v11c retention)

- Both touch `Customer` (you read, v11c writes new fields). No conflict.
- `seed_data.py`: v11a seeds a `RotatingCheckinKey` for the demo store. v11c may backfill `cohort` fields. Different sections of the same file — keep-both merge.
- Migrations: v11a adds 1-2 migrations (key model + Store field). v11c adds 1 (Customer fields). Different. Merge migration only if numbers collide.
- Admin pages: v11a adds `/admin/settings/checkin/`. v11c adds cohort filter to customer list. Different pages.
