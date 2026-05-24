---
name: staff-auth
description: Real Django session-based staff authentication. Retires the localStorage placeholder `useAuth()` and the `/login` page. Adds a server-rendered staff login form, session-backed `request.user`, a `/api/staff/me/` introspection endpoint, and a per-tab StaffSessionProvider that route-guards every `/admin/*` page. Customer auth (v7 phone+OTP) is unaffected.
status: backlog
created: 2026-05-24T13:00:00Z
---

# PRD: staff-auth

## Executive Summary

Today every `/admin/*` page is gated only by a localStorage check (`useAuth().user?.role === "staff"`) that a customer can spoof from the browser console in 5 seconds. The PRD's docstring on `frontend/src/lib/auth.tsx` admits this: *"Dummy auth for demo purposes — real NextAuth integration in Wave 1."* Wave 1 never came. Every backend API view runs with `permission_classes: list = []` per the project convention, so the backend trusts whoever calls it.

This epic ships real, server-authoritative staff auth: a Django session cookie issued by a real login form, an introspection endpoint (`/api/staff/me/`) that returns the authenticated user or 401, and a `StaffSessionProvider` that wraps the admin layout and redirects to `/staff/login` on 401. Customer-facing v7 OTP auth is left untouched (different cookie, different middleware, different surface). The placeholder `/login` page + `lib/auth.tsx` are retired.

## Problem Statement

Concretely:

1. **Trivially spoofable admin access** — `localStorage.setItem("playdesk.user", JSON.stringify({name:"x",role:"staff"}))` in any browser console grants full admin UI. The admin UI then makes API calls that the backend services unconditionally because `permission_classes` is empty everywhere.
2. **No real staff identity on the server** — every admin action records `author=None` (or the literal demo-staff seed user) on `CustomerNote`, `PointTransaction`, etc. There's no audit trail tied to a real person.
3. **`/login` is misleading** — the page lets the customer click "Customer (Guest)" and be sent to `/`. v7 customer-portal ships the real phone+OTP login at `/s/[slug]/account`, so we now have two competing customer auth surfaces (one fake, one real) and zero real staff auth.
4. **Wave 1 promise unmet** — the comment in `auth.tsx` flags this as known tech debt. Every code reader trips over it.

The fix isn't a new auth library — Django ships session auth out of the box, the project already has `AUTH_USER_MODEL` set, and `django.contrib.sessions.middleware.SessionMiddleware` is registered. The work is wiring the existing pieces and retiring the placeholders.

## User Stories

- **As a chain owner**, I navigate to `/admin` for the first time, get redirected to `/staff/login`, enter `manager@playdesk` + my password, land on the admin dashboard. The session persists across browser restarts for 14 days.
  - *Acceptance:* `/api/staff/login/` POST creates a Django session, sets the `sessionid` cookie (HttpOnly + Secure + SameSite=Lax). `/admin` gates on `/api/staff/me/` 200 vs 401.
- **As a staff user**, my actions (creating a customer note, adjusting points, ringing up a refund) are attributed to my real username in the audit logs / admin UI. Anonymous attribution disappears.
  - *Acceptance:* All views that currently do `author = request.user if request.user.is_authenticated else None` now reliably resolve `request.user` to the logged-in staff user. The existing seed `demo_staff` user keeps working for legacy tests.
- **As a staff user**, "Log out" in the admin nav clears the session cookie and lands me back on `/staff/login`.
- **As a customer**, the placeholder `/login` page no longer exists — clicking the link in any old email / bookmark sends me to my store's customer portal (`/s/<default-slug>/account`) instead.
- **As a developer**, I can grep for `useAuth` and find ZERO call sites — the hook + provider + localStorage glue are gone.
- **As the security team**, an admin endpoint hit without a session returns 401, not 200. (This requires per-view enforcement, see §Functional Requirements.)

## Functional Requirements

1. **Backend session endpoints** — new `backend/api/views_staff_auth.py`:
   - `POST /api/staff/login/` body `{username, password}` → on success, calls `django.contrib.auth.login(request, user)` (creates session) and returns `{id, username, is_superuser, is_staff}`. On failure → 401 with `{detail: "Invalid credentials"}`. Rate-limited: 5 attempts per username per 15 min via the Django cache.
   - `POST /api/staff/logout/` → calls `django.contrib.auth.logout(request)`. Always 200.
   - `GET /api/staff/me/` → 200 with `{id, username, is_superuser, is_staff, store_memberships: []}` if authenticated, else 401 `{detail: "Not authenticated"}`. **This endpoint is the entire auth gate from the frontend's perspective.**
2. **Per-view enforcement on admin endpoints** — opt-in by URL prefix:
   - Add `StaffOnlyMiddleware` at `backend/core/middleware.py` that gates every URL matching `/api/admin/*` on `request.user.is_authenticated AND request.user.is_staff`. Anonymous → 401, non-staff user → 403.
   - This is the load-bearing change. The PRDs' "no API-level permission gates" convention was always wrong for admin endpoints — v10 corrects it.
   - Customer endpoints (`/api/me/*`, `/api/customer-auth/*`, `/api/quote/`, `/api/bookings/`, etc.) are NOT touched — they keep their existing customer-cookie / public semantics.
3. **Seed a demo staff user** — extend `seed_data.py`:
   - Create `playdesk_staff` user with password `playdesk_staff_demo_pw` (set via `set_password`).
   - Mark `is_staff=True`, `is_active=True`.
   - Idempotent: `get_or_create` keyed on username.
   - Print the credentials at the end of the seed output so developers can log in.
4. **`/staff/login/` page** (Next.js):
   - Server component reads `sessionid` cookie. If a `/api/staff/me/` call from the SSR side succeeds, redirect to `/admin`. Else render the login form.
   - Client form: username + password fields, submit POSTs to `/api/staff/login/`, on 200 → `router.push("/admin")`, on 401 → inline error.
   - "Forgot password" link → out of scope, links to a stub page that says "contact your administrator".
5. **`StaffSessionProvider` + `useStaffSession()` hook** (`frontend/src/lib/staff-session.tsx`):
   - On mount: calls `/api/staff/me/`. State: `{user, ready, error}`.
   - 401 → `user=null`, fires a `router.replace("/staff/login?next=" + pathname)` (only if pathname starts with `/admin/`).
   - `logout()` action: POSTs `/api/staff/logout/`, clears state, redirects to `/staff/login`.
   - `<StaffSessionProvider>` wraps the existing admin layout at `frontend/src/app/admin/layout.tsx`.
6. **Migrate existing admin pages** — every file under `frontend/src/app/admin/*` that currently calls `useAuth()` switches to `useStaffSession()`. ~10 files, mechanical rename, no behavior change beyond the gate becoming real.
7. **Retire `/login` + `lib/auth.tsx`**:
   - Delete `frontend/src/app/login/page.tsx`. Add a new `frontend/src/app/login/page.tsx` that server-redirects (302) to `/s/<default-slug>/account` (use the same default-slug lookup as `frontend/src/app/page.tsx`).
   - Delete `frontend/src/lib/auth.tsx`.
   - Remove `<AuthProvider>` from `frontend/src/app/layout.tsx`.
8. **Admin nav adds username + Logout button** — small UX completion. The header chip says `Signed in as manager@playdesk` with a Logout link.
9. **`adminFetch` (v6) gets a 401 handler** — if any admin API call returns 401 mid-session (session expired), the wrapper triggers `useStaffSession()`'s logout flow.

## Non-Functional Requirements

- **Session security**: Django default — `sessionid` is HttpOnly + Secure (in production via `SESSION_COOKIE_SECURE=True`) + SameSite=Lax + 14-day expiry (configurable via `SESSION_COOKIE_AGE`).
- **No third-party auth library** — Django's built-in is sufficient at this scale. NextAuth + an OAuth provider is a future epic if staff auth needs SSO.
- **Backward compat for tests**: every existing test that creates a `User` via `User.objects.create_user(...)` keeps working. Tests that previously assumed open admin endpoints get a `client.force_login(user)` shim — straightforward refactor, ~30 test files affected (mostly `tests/test_admin_*.py`).
- **CSRF**: Django session auth enforces CSRF on unsafe methods by default. The frontend's `adminFetch` already sends the `X-CSRFToken` header — verify it's present, add it if missing.
- **Performance**: `/api/staff/me/` is one DB query (the user row). The middleware adds one cache lookup per `/api/admin/*` request. Negligible.

## Dependencies

- `django.contrib.auth` + `django.contrib.sessions` (already in `INSTALLED_APPS`).
- v6 multi-location (in main) — `adminFetch` wrapper to extend with 401 handling.
- No new pip / npm deps.

## Out of Scope

- SSO / OAuth / SAML.
- Per-store staff membership (a user can access ALL stores in v10; per-store ACL is a future epic when chains have outsourced staff).
- Password reset via email.
- 2FA / MFA.
- Audit log table beyond what already exists (`CustomerNote.author`, `PointTransaction.author`).
- API tokens for programmatic staff access.
- Replacing customer OTP — v7's auth is correct and stays.

## Expected Conflict Zones with Peer Epic (v10b checkin)

- Both add migrations to `core` — additive, merge migration if numbers collide.
- v10b adds `Booking.checked_in_at` + `check_in_token` + `BookingStatus.CHECKED_IN`. v10a doesn't touch `Booking`. No conflict.
- Admin pages: v10b adds a check-in badge to booking detail/list. v10a wraps admin layout with a new provider. Different code paths.
- `settings.py`: v10a may add `SESSION_COOKIE_AGE`, `LOGIN_URL`. v10b doesn't touch settings.
- `seed_data.py`: v10a adds `playdesk_staff` user. v10b adds check-in tokens for seeded bookings. Different sections of the same file — merge with keep-both.
