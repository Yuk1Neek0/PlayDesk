---
name: checkin
status: completed
created: 2026-05-24T13:00:00Z
updated: 2026-05-24T15:00:00Z
progress: 100%
prd: .claude/prds/checkin.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/195
---

# Epic: checkin

## Overview

Per-booking check-in flow: each booking gets a unique 8-char `check_in_token` at creation, the SMS confirmation includes a `/c/<token>` link, the customer taps on arrival and one click flips the booking to a new `CHECKED_IN` status with `checked_in_at` timestamped. Admin booking list/detail surfaces the state with manual override buttons. A new `auto_complete_checked_in` sweeper promotes checked-in bookings to `COMPLETED` after their end_time + grace period, triggering the existing `booking_thank_you` SMS.

## Architecture Decisions

- **Per-booking tokens, not per-resource QR stickers.** v10b targets the booking lifecycle gap, not station identity. A "scan PS5 station 3" flow is a separate concern (asset tracking, walk-up bookings) and gets its own future epic.
- **8 chars base32 (no ambiguous chars) = 40 bits entropy.** Fits in an SMS comfortably alongside the rest of the confirmation. 10^12 keyspace is well past brute-force threat for PlayDesk's request rate.
- **Token is public-by-design.** Anyone who has the URL can check in. Threat model: an attacker who learns someone else's token can only check them in early — no PII leak beyond first name + resource + start time. Acceptable; the URL is meant to be shareable in case the customer hands it to a friend.
- **`CHECKED_IN` between `CONFIRMED` and `COMPLETED`.** Doesn't replace COMPLETED — the sweeper promotes through. Existing consumers of COMPLETED keep working.
- **Idempotent everything.** Double-tap on check-in is fine. Re-running the sweeper is fine. Re-running the data migration is fine.
- **Sweeper is a management command + crontab, not a Celery beat task.** Project has no broker; adding one for one job is over-engineering. Cron is enough.
- **Extend `booking_confirmation` template, don't add a new SMS.** One SMS at booking time saves the customer a notification and saves us a Twilio segment.

## Technical Approach

### Backend Services
- `backend/core/models.py::Booking` — add `check_in_token: CharField(max_length=12, unique=True, db_index=True, blank=True)` and `checked_in_at: DateTimeField(null=True, blank=True)`. Add `BookingStatus.CHECKED_IN = "checked_in"` choice.
- `backend/core/tokens.py` (new) — `generate_check_in_token()` returns an 8-char base32 string (no `0`/`O`/`1`/`I`/`l`), retrying on uniqueness collision.
- `backend/core/migrations/000X_booking_check_in.py` — additive (token + checked_in_at + status choice).
- `backend/core/migrations/000Y_backfill_check_in_token.py` — RunPython that fills tokens for every existing booking where `check_in_token=""` (idempotent).
- `backend/api/serializers.py::BookingCreateSerializer.create` — assign `check_in_token = generate_check_in_token()` before save.
- `backend/api/serializers.py::BookingSerializer` — add `check_in_token`, `checked_in_at` to read-only fields.
- `backend/api/views_checkin.py` (new) — `GET /api/c/<token>/`, `POST /api/c/<token>/check-in/`, `POST /api/admin/bookings/<pk>/check-in/`, `POST /api/admin/bookings/<pk>/undo-check-in/`. Admin variants are write-only and behind v10a's `StaffOnlyMiddleware` once merged (cross-epic graceful: if v10a lands later, the admin endpoint is just open).
- `backend/outbound/templates.py` — extend `booking_confirmation` body with `" Check in on arrival: {checkin_url}"`.
- `backend/outbound/api.py` (or wherever enqueue happens for `booking_confirmation`) — pass `checkin_url = settings.SITE_URL + "/c/" + booking.check_in_token` into the template context.
- `backend/core/management/commands/auto_complete_checked_in.py` (new) — sweep `Booking.objects.filter(status="checked_in", end_time__lt=now()-30min)`, flip to `COMPLETED`, enqueue `booking_thank_you` SMS.

### Frontend Components
- `frontend/src/app/c/[token]/page.tsx` (new) — server component fetches `GET /api/c/<token>/`, renders a centered card with store branding (reuses `fetchStoreBrand`), customer first name, "I'm here" button. State variants for cancelled / already-checked-in / pending_payment.
- `frontend/src/app/c/[token]/CheckInClient.tsx` (new) — client component handling the POST + success transition.
- `frontend/src/app/admin/bookings/page.tsx` (or wherever the bookings list is) — add a "Check-in" column showing `checked_in_at` or "—".
- `frontend/src/app/admin/bookings/[id]/page.tsx` — add a Check-in panel with "Manual check-in" + "Undo check-in" buttons.
- `frontend/src/components/admin/checkin-badge.tsx` (new, small) — re-used by list + detail.

### Infrastructure
- No new pip / npm deps.
- 2 additive core migrations.

## Implementation Strategy

Sequential, mostly because of schema dependencies:

1. **#196 Schema** — fields + migration + backfill + token generator. Everything else depends on the field existing.
2. **#197 Public check-in endpoints + page + SMS link** — `/api/c/<token>/`, `/c/[token]/`, BookingCreateSerializer assigns the token, SMS template extension. The customer-facing path lights up.
3. **#198 Admin manual buttons + booking list/detail badge** — staff path completes.
4. **#199 Sweeper** — `auto_complete_checked_in` management command + tests. Closes the loop to COMPLETED.
5. **#200 Tests + e2e** — backend unit + frontend unit + Playwright `checkin.e2e.ts`.

Single agent, sequential within the epic. Estimated wall-time: ~45-60 min.

## Task Breakdown Preview

- 196 — Booking.check_in_token + checked_in_at + CHECKED_IN status + 2 migrations + token generator
- 197 — Public /api/c/<token>/ + /c/[token]/ page + SMS link in booking_confirmation
- 198 — Admin manual check-in + undo endpoints + booking list/detail check-in badge
- 199 — `auto_complete_checked_in` management command + sweeper tests
- 200 — Tests (backend unit for endpoints/sweeper + frontend unit + checkin.e2e.ts)

## Dependencies

- Hard: `multi-location` (v6, in main) — `fetchStoreBrand` for the check-in page header.
- Hard: `outbound` (v4, in main) — SMS template for the check-in link + `booking_thank_you` template for the sweeper.
- Soft: `staff-auth` (v10a, parallel epic) — if v10a lands first, admin endpoints are auto-gated by `StaffOnlyMiddleware`; if v10b lands first, they're open until v10a merges. Both states acceptable.

## Success Criteria (Technical)

- Every new booking has a populated `check_in_token` (BookingCreateSerializer assigns it).
- The data migration backfills tokens for every existing booking with zero collisions on a database of 100 sample bookings.
- `GET /api/c/<token>/` returns `can_check_in: true` for a CONFIRMED booking, `false` with helpful `message` for every other state.
- `POST /api/c/<token>/check-in/` is idempotent: a second POST returns 200 with the same payload.
- Sweeper test: a CHECKED_IN booking with `end_time` 60 min ago gets promoted to COMPLETED + the `booking_thank_you` SMS is enqueued (mock outbound).
- e2e: scan a generated token URL → see the welcome card → tap → see ✓ Welcome → DB confirms `checked_in_at` populated.

## Estimated Effort

- Single agent, ~45-60 min wall-time.

## Tasks Created
- [ ] #196 - Booking schema + check_in_token + checked_in_at + CHECKED_IN status + token generator (parallel: false)
- [ ] #197 - Public /api/c/<token>/ + /c/[token]/ page + SMS link in booking_confirmation (parallel: false, depends on 196)
- [ ] #198 - Admin manual check-in + undo + booking list/detail badge (parallel: false, depends on 197)
- [ ] #199 - auto_complete_checked_in management command + sweeper (parallel: false, depends on 197)
- [ ] #200 - Tests (backend unit + frontend unit + checkin.e2e.ts) (parallel: false, depends on 198, 199)

Total tasks: 5
