---
name: checkin
description: Per-booking check-in flow. Each confirmed booking gets a unique URL-safe `check_in_token`; the customer scans the QR (or taps the link in their SMS confirmation) at the store and lands on /c/[token], one-tap check-in flips the booking to a new CHECKED_IN status + stamps `checked_in_at`. Admin booking list/detail surfaces the check-in state; manual check-in / undo from staff for edge cases (lost phone, walk-ins).
status: backlog
created: 2026-05-24T13:00:00Z
---

# PRD: checkin

## Executive Summary

PlayDesk's booking lifecycle has a gap: `confirmed → ??? → completed`. There's no state in between, no event when the customer actually walks in. Today staff either remember who showed up or eyeball the room. The v3 one-qr engagement system has chips for Google Review, Instagram, WiFi — but no "I'm here, here's my booking" chip.

This epic ships per-booking check-in: each booking gets a unique short token at creation time, the booking-confirmation SMS includes a `/c/<token>` URL, the customer scans/taps it on arrival and one tap flips `booking.status` from `CONFIRMED` to a new `CHECKED_IN` state with `checked_in_at` timestamped. Staff see the check-in badge on the booking list/detail, can manually check-in walk-ins, and can undo erroneous check-ins. The state machine becomes `pending → pending_payment → confirmed → checked_in → completed`, with `cancelled` orthogonal.

It deliberately avoids per-resource QR stickers (that's a v11 idea — "scan the QR taped to PS5 station 3 to claim it"). v10b ships only per-booking tokens via SMS / portal link.

## Problem Statement

The customer journey has a blind spot:

```
[book online]  →  [SMS confirmation]  →  ???  →  [staff marks complete in admin]
                                          ↑
                                  here be dragons
```

Specifically:

- **No arrival signal.** Staff don't know who's at the door without asking for a name + checking the booking list. With 10 confirmed bookings on a Friday night, the manual lookup creates a 30-second friction at every entry.
- **No automatic completion path.** `BookingStatus.COMPLETED` exists but nothing transitions to it without staff manually editing the row. Loyalty points (v4) backfill from booking history requires accurate completed state; today it depends on staff diligence.
- **No-show detection is impossible.** A booking that's confirmed but the customer never showed has no distinguishing data — staff would need to manually mark it. The `no_show_followup` outbound template exists but has no trigger.
- **Existing QR scope is engagement, not transactional.** The `QRAction` system (v3) is for "after the visit" actions: Google Review, follow on Instagram. It's deliberately not booking-aware. Bolting "check me in" onto it would muddy the model — check-in needs the booking_id, the QR chips are store-scoped.

The architectural fit: a new dedicated endpoint at `/c/<token>` that resolves a booking and accepts the check-in mutation. Short URLs that fit in an SMS. State changes that drive automatic completion later (or at least let staff process bookings in bulk: "everyone checked-in 2h ago → mark completed").

## User Stories

- **As a customer**, I get an SMS at booking time with my check-in link: *"Booking confirmed for Fri 7pm, PS5 Station 2. Check in on arrival: playdesk.com/c/9F3Kx2"*. On arrival I tap the link, see "Welcome [name], tap to check in", tap, get "✓ Checked in — please enjoy your session". My loyalty points auto-credit per v4's `total_visits` increment.
  - *Acceptance:* The token resolves to my booking; check-in idempotent (a second tap shows "already checked in"); state flips to CHECKED_IN; `checked_in_at = now()`.
- **As a customer**, if I try to check in for a cancelled booking, the page says "This booking was cancelled — see staff for help" rather than silently failing.
- **As a customer**, the check-in link in my SMS works even if I'm not logged in to the customer portal — token is the only credential needed.
  - *Acceptance:* Token has enough entropy (8+ chars from a base32 alphabet) to make brute-forcing infeasible at PlayDesk scale.
- **As staff**, the admin booking list shows a small badge: "✓ Checked in 7:03pm" (or "—" for confirmed-but-not-yet-arrived). I can filter the list by check-in state.
- **As staff**, on the booking detail I see the check-in timestamp + a "Manual check-in" button (for walk-ins who lost their SMS) and an "Undo check-in" button (for accidental clicks).
  - *Acceptance:* Both buttons emit a `CustomerNote(author=request.user, body="manually checked in"/"check-in undone")` for audit.
- **As a chain owner**, on Sunday morning I run `python manage.py auto_complete_checked_in` (or have a cron run it) — any booking that's been CHECKED_IN for more than `[duration]` hours gets flipped to COMPLETED, triggering the `booking_thank_you` SMS via v4 outbound.
  - *Acceptance:* Idempotent — re-running the command is a no-op for already-completed rows.

## Functional Requirements

1. **Booking schema**:
   - `Booking.check_in_token: CharField(max_length=12, unique=True, db_index=True, blank=True)` — base32 alphabet (no ambiguous chars `0`/`O`/`1`/`I`/`l`), 8 chars (~40 bits entropy = 1.1 trillion combos).
   - `Booking.checked_in_at: DateTimeField(null=True, blank=True)`.
   - `BookingStatus.CHECKED_IN = "checked_in", "Checked in"` (insert between CONFIRMED and COMPLETED).
2. **Migrations**:
   - Migration A: add fields nullable, add the new status choice.
   - Migration B (data): backfill `check_in_token` for every existing confirmed booking (random short token). Future bookings get a token at create time via the `BookingCreateSerializer.create`.
   - Token generator: `core/tokens.py::generate_check_in_token()` — 8 chars, base32 minus ambiguous. Guarantees uniqueness via retry loop (1 collision in ~10^10 is fine to retry).
3. **Token assignment on booking-create** — `BookingCreateSerializer.create` writes `check_in_token = generate_check_in_token()` before save.
4. **Public check-in endpoints**:
   - `GET /api/c/<token>/` → `{booking_id, status, customer_name, resource_name, start_time, end_time, store_slug, can_check_in: bool, message: str}`.
     - `can_check_in=True` if status is `CONFIRMED` and `checked_in_at is None`.
     - `can_check_in=False` if status is `CANCELLED` / `PENDING_PAYMENT` / already `CHECKED_IN` / `COMPLETED` (with a helpful `message` field per state).
   - `POST /api/c/<token>/check-in/` → if `can_check_in` per the GET: flips status to `CHECKED_IN`, sets `checked_in_at = now()`, returns the same payload. Idempotent: a second POST returns 200 with the same payload (not 409).
   - Token-not-found → 404 with a friendly message.
5. **Public check-in page** — `frontend/src/app/c/[token]/page.tsx`:
   - Server-side fetch of `GET /api/c/<token>/`.
   - Renders a centered card: store branding (reuses `fetchStoreBrand`), customer first name, "Tap to check in — [resource] at [time]" with a big "I'm here" button.
   - On tap: client-side POST to `/api/c/<token>/check-in/`, renders "✓ Welcome, [name] — enjoy your session" success state.
   - State-specific renders for cancelled / already-checked-in / pending payment.
6. **SMS template** — extend `booking_confirmation` to include the check-in link OR add a new template `booking_checkin_link` that fires immediately after `booking_confirmation`:
   - Recommended: append the line `"Check in on arrival: {checkin_url}"` to the existing template's body. Single SMS, single template, no template explosion.
   - The `outbound` enqueue path needs to know the absolute URL — read `settings.SITE_URL + "/c/" + booking.check_in_token`.
7. **Admin booking list badge** — `frontend/src/app/admin/bookings/page.tsx`: add a column "Check-in" showing the timestamp (or "—") + filter dropdown "all / not yet / checked in".
8. **Admin booking detail panel** — `frontend/src/app/admin/bookings/[id]/page.tsx` (or wherever the detail is):
   - Section "Check-in": shows `checked_in_at` timestamp + "Manual check-in" button (POSTs `/api/admin/bookings/{id}/check-in/`) + "Undo check-in" button (POSTs `/api/admin/bookings/{id}/undo-check-in/`).
   - Both staff actions write a `CustomerNote(body="Manually checked in by staff")` for audit.
9. **`python manage.py auto_complete_checked_in`** — sweeper that promotes CHECKED_IN bookings to COMPLETED:
   - Promotion rule: `status=CHECKED_IN AND end_time < now() - 30min` (30-minute grace so a customer finishing late isn't prematurely marked done).
   - On promotion: enqueues `booking_thank_you` SMS via v4 outbound.
   - Idempotent + safe to re-run hourly via cron.

## Non-Functional Requirements

- **URL length** — `/c/<8-char-token>` is 11 chars; a `playdesk.com/c/9F3Kx2` URL fits in a single SMS segment alongside the booking confirmation text without splitting.
- **Token security** — 40 bits is plenty for the threat model. Tokens are public-by-design (anyone with the URL can check in) but enumeration is infeasible. A malicious actor who finds someone else's token can only check them in early — no PII leak beyond first name + resource + start time. Acceptable.
- **Backward compatibility** — existing tests pass after migration (the new `check_in_token` field is populated by the data migration; existing `BookingStatus` consumers handle the new value via a fallback). `BookingStatus.COMPLETED` consumers continue to work — sweeper still gets bookings there.
- **Idempotent everything** — check-in POST is idempotent (re-tap is fine). Sweeper is idempotent (re-run is no-op). Migration backfill is idempotent (only fills empty `check_in_token` fields).
- **No new pip / npm deps.**

## Dependencies

- v6 multi-location (in main) — `fetchStoreBrand` for the check-in page header, store-scoped URLs.
- v7 customer-portal (in main) — admin booking detail page exists to extend with the check-in panel (or admin bookings list, depending on structure).
- v4 outbound (in main) — SMS template for the check-in link + the `booking_thank_you` template for the sweeper.

## Out of Scope

- Per-resource QR stickers ("scan PS5 station 3's QR to start"). Future epic.
- Geofenced auto-check-in (browser geolocation gating). Privacy + reliability risk.
- Staff-side bulk check-in ("everyone arriving at 7pm got here, mark them all"). Future.
- Push notifications to staff when a customer checks in. Out of scope; admin polling + dashboard refresh sufficient.
- Customer-side "I want to cancel because I haven't been checked in" — orthogonal flow.
- Loyalty points doubled-up on check-in (no, points stay tied to booking COMPLETED).

## Expected Conflict Zones with Peer Epic (v10a staff-auth)

- Migrations on `core`: v10b adds `Booking.check_in_token`, `checked_in_at`, status choice. v10a adds nothing to `core` models. Merge migration only if numbers collide.
- `seed_data.py`: v10b backfills check-in tokens for the seeded confirmed booking. v10a adds the demo staff user. Different sections → keep-both merge.
- Admin booking detail page: v10b adds a check-in panel. v10a wraps the admin layout in a provider. Different code paths → no conflict.
- `BookingSerializer`: v10b adds `check_in_token`, `checked_in_at` to the read-only fields. v10a doesn't touch.
- `outbound/templates.py`: v10b extends `booking_confirmation` body OR adds `booking_checkin_link`. v10a doesn't touch.
