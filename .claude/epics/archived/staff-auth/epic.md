---
name: staff-auth
status: completed
created: 2026-05-24T13:00:00Z
updated: 2026-05-24T15:00:00Z
progress: 100%
prd: .claude/prds/staff-auth.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/189
---

# Epic: staff-auth

## Overview

Real Django session-based staff authentication. Three new API endpoints (`login`, `logout`, `me`), one new middleware that gates `/api/admin/*`, one new frontend session provider that route-guards every admin page, one new login page, ~10 mechanical frontend renames (`useAuth` → `useStaffSession`), retirement of the placeholder `/login` + `auth.tsx`. Reverses the project's "no API-level permission gates" convention for `/api/admin/*` only — customer endpoints are untouched.

## Architecture Decisions

- **Django session auth, not NextAuth / OAuth.** Project already has `django.contrib.auth` + `SessionMiddleware` wired. Zero new deps. NextAuth would be over-engineering for one customer chain with a handful of staff users; revisit if SSO is ever needed.
- **Middleware-based admin gate, not per-view decorators.** One file (`StaffOnlyMiddleware`) gates every `/api/admin/*` URL on `request.user.is_authenticated AND request.user.is_staff`. Per-view `@login_required` would mean 20 decorators to maintain and one forgotten endpoint = security hole. Middleware is fail-closed.
- **`/api/staff/me/` is the entire frontend auth surface.** Frontend never needs to know about Django sessions, CSRF tokens, or the user model internals — it just polls `/api/staff/me/` on mount and route-guards on 401. Clean separation.
- **Customer auth (v7) untouched.** v7 ships `pd_customer_session` cookie + `CustomerSessionMiddleware`. Staff auth is parallel: `sessionid` cookie + Django auth middleware. Two namespaces, no overlap, no privilege confusion. The reverse would be catastrophic (a customer accidentally getting staff perms).
- **Retire `/login` as redirect, not 404.** Old bookmarks / email links don't 404 — they 302 to `/s/<default-slug>/account` (customers) since staff bookmarks would never have used `/login` in the first place. Cheaper than tracking down every reference.
- **Reverse the "no API perms" convention only for admin endpoints.** The convention made sense when there was no real auth. Now there is. Document the reversal in the middleware docstring + the epic so future readers don't undo it.

## Technical Approach

### Backend Services
- `backend/api/views_staff_auth.py` (new) — `StaffLoginView`, `StaffLogoutView`, `StaffMeView`. Login uses `django.contrib.auth.authenticate` + `login(request, user)`. Rate-limited via the cache (5 attempts per username per 15 min). Logout calls `logout(request)`. Me returns user fields or 401.
- `backend/core/middleware.py::StaffOnlyMiddleware` (new) — gates every URL matching `/api/admin/*` on `request.user.is_authenticated AND request.user.is_staff`. Anonymous → 401. Non-staff user → 403. Registered after `SessionMiddleware` + `AuthenticationMiddleware`.
- `backend/config/settings.py` — set `SESSION_COOKIE_AGE = 14 * 24 * 3600` (14 days). `SESSION_COOKIE_SAMESITE = "Lax"`. `LOGIN_URL = "/staff/login/"`.
- `backend/core/management/commands/seed_data.py` — add `playdesk_staff` user with `is_staff=True`, password set via `set_password`. Idempotent.
- `backend/api/urls.py` — wire the three new endpoints under `/api/staff/`.

### Frontend Components
- `frontend/src/lib/staff-session.tsx` (new) — `StaffSessionContext`, `<StaffSessionProvider>`, `useStaffSession()` hook. On mount calls `/api/staff/me/`; 401 → `router.replace("/staff/login?next=" + pathname)` if pathname starts with `/admin/`.
- `frontend/src/app/staff/login/page.tsx` (new) — server component checks session cookie; if valid, 302 to `/admin`; else render the login form (client component). Form POSTs to `/api/staff/login/`, on 200 → `router.push(next || "/admin")`.
- `frontend/src/app/admin/layout.tsx` — wrap children in `<StaffSessionProvider>`. Add username chip + Logout button to the existing nav.
- `frontend/src/lib/admin-fetch.ts` — extend to handle 401 by triggering the session provider's logout flow.
- Every `frontend/src/app/admin/**/*.tsx` that imports `useAuth` — rename to `useStaffSession`. ~10 files, mechanical.
- `frontend/src/app/login/page.tsx` — replace with a 302-redirect to `/s/<default>/account` (mirrors `app/page.tsx`'s default-slug lookup).
- `frontend/src/lib/auth.tsx` — DELETE.
- `frontend/src/app/layout.tsx` — remove `<AuthProvider>`.

### Infrastructure
- No new pip / npm deps.
- One additive migration (if any — most likely none, Django's `auth_user` table is already there from initial Django migrations).

## Implementation Strategy

Sequential, because each task depends on the prior:

1. **#190 Backend auth endpoints + seed user** — `/api/staff/{login,logout,me}/` + rate limiter + `playdesk_staff` user. Until this lands, no frontend work can call real endpoints.
2. **#191 `StaffOnlyMiddleware` + test shim** — gate the admin API. Existing tests get a `pytest fixture` that does `client.force_login(staff_user)`. Once green, the admin API is locked.
3. **#192 Frontend `StaffSessionProvider` + login page** — the session-detection surface. Standalone — can be built/tested without touching existing admin pages yet.
4. **#193 Migrate admin pages + retire `/login` + `auth.tsx`** — the big mechanical change. All `useAuth` call sites swap to `useStaffSession`. `/login` becomes a 302. `auth.tsx` deleted. Layout wrap added. After this lands, the real auth gate is live for users.
5. **#194 Tests + e2e** — backend unit tests for the new endpoints + middleware + rate limit + the test shim. Frontend test for the StaffSessionProvider mount behavior. e2e Playwright covers the login → access admin → logout cycle.

Single agent, sequential within the epic. Estimated wall-time: ~45-60 min.

## Task Breakdown Preview

- 190 — Backend `/api/staff/{login,logout,me}/` + rate limiter + `playdesk_staff` seed user
- 191 — `StaffOnlyMiddleware` on `/api/admin/*` + test fixture `force_login_staff`
- 192 — `StaffSessionProvider` + `useStaffSession` hook + `/staff/login/` page + adminFetch 401 handler
- 193 — Migrate admin pages from `useAuth` → `useStaffSession`; retire `/login` + `auth.tsx`; admin nav username + Logout
- 194 — Tests (backend unit + frontend unit + Playwright e2e `staff-auth.e2e.ts`)

## Dependencies

- Hard: `django.contrib.auth` + `django.contrib.sessions` (in `INSTALLED_APPS`).
- Hard: `multi-location` (v6, in main) — `adminFetch` to extend with 401 handling.
- Soft: every existing test that hits `/api/admin/*` (~30 test files) needs a `force_login_staff` fixture call. Task #191 ships the fixture; the migration is mechanical.

## Success Criteria (Technical)

- `curl /api/admin/customers/` without a session → 401.
- `curl /api/admin/customers/` with non-staff session → 403.
- `curl /api/admin/customers/` with staff session → 200.
- Frontend devtools `localStorage.setItem("playdesk.user", ...)` → ignored, redirects to `/staff/login` on next admin nav.
- Existing 687-test backend suite passes after the `force_login_staff` shim is applied to admin-hitting tests.
- `staff-auth.e2e.ts` happy path: visit `/admin` → redirect to `/staff/login` → enter `playdesk_staff` creds → land on `/admin` → click Logout → redirect to `/staff/login`.

## Estimated Effort

- Single agent, ~45-60 min wall-time.

## Tasks Created
- [ ] #190 - Backend /api/staff/ login/logout/me + rate limiter + seed staff user (parallel: false)
- [ ] #191 - StaffOnlyMiddleware on /api/admin/* + force_login_staff test fixture (parallel: false, depends on 190)
- [ ] #192 - StaffSessionProvider + useStaffSession + /staff/login/ page + adminFetch 401 (parallel: false, depends on 190)
- [ ] #193 - Migrate admin pages useAuth→useStaffSession; retire /login + auth.tsx; nav username + Logout (parallel: false, depends on 192)
- [ ] #194 - Tests (backend unit + frontend unit + staff-auth.e2e.ts) (parallel: false, depends on 191, 193)

Total tasks: 5
