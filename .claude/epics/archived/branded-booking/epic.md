---
name: branded-booking
status: completed
created: 2026-05-24T01:00:22Z
updated: 2026-05-24T02:03:46Z
progress: 100%
prd: .claude/prds/branded-booking.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/137
---

# Epic: branded-booking

## Overview

One new public endpoint (`/api/public/store-brand/`), one new SSR helper (`store-brand.ts`), one edit to the booking page (`app/page.tsx`) to read brand SSR-side, one refactor of the QR page (`app/qr/[slug]/page.tsx`) to use the shared helper. No database changes — `Store.brand` already exists from one-qr.

## Architecture Decisions

- **One small endpoint, two callers.** Rather than two parallel implementations (one for `/qr/[slug]` SSR-fetch and one for `/`), introduce a shared frontend helper that hits a shared endpoint. Mirrors the project's convention of single sources of truth (cf. `normalize_phone` from retention).
- **Single-store assumption stays.** The endpoint returns the "default store" (the one returned by `Store.objects.first()`, matching the existing app-wide assumption). Multi-location URL routing is explicitly v6 — locking in `/book/[slug]` now would conflict with the multi-location plan.
- **Accent validation happens server-side.** Returning an unvalidated accent value would let an admin typo break the page. The endpoint regex-validates against a tiny grammar (`oklch(...)`, `#xxxxxx`, `rgb(...)`); invalid → returns `null` and the frontend falls back to the default accent.
- **Cache headers on the endpoint.** `Cache-Control: public, max-age=60` because brand changes are admin-driven and rare, and the booking page hits this on every SSR render.

## Technical Approach

### Frontend Components
- `frontend/src/lib/store-brand.ts` (new) — `fetchStoreBrand(): Promise<StoreBrand>` with `{ name: string, logo_url: string | null, accent: string | null }`. SSR-side fetch using the BACKEND_ORIGIN pattern (see `app/qr/[slug]/page.tsx` for the established shape).
- `frontend/src/app/page.tsx` — extend the existing booking-page SSR loader to also call `fetchStoreBrand()`. Pass through to the page component, which:
  - Replaces the hardcoded SVG logo with `<Image src={logo_url} />` when `logo_url` is present.
  - Sets the inline style `--pd-accent: ${accent}` on the page wrapper when `accent` is present (CSS variables already drive the primary CTAs).
- `frontend/src/app/qr/[slug]/page.tsx` — refactored: the existing inline brand read becomes a call to `fetchStoreBrand()`. No render change.

### Backend Services
- `backend/api/views_public.py` (new — name TBD; could also extend `views.py`) — `StoreBrandView(APIView)`:
  - `GET /api/public/store-brand/` returns `{ name, logo_url, accent }`.
  - Accent is regex-validated; invalid → `null`.
  - No auth (it's a public branding signal — already visible on `/qr/[slug]` to any anonymous visitor).
  - 60-second cache header.
- `backend/api/urls.py` — add the new route.

### Infrastructure
- No new env vars, no new pip deps, no migration.

## Implementation Strategy

Endpoint + validation first, then frontend helper, then booking-page integration in parallel with the QR-page refactor (the two consumers can land at the same time). The QR refactor must preserve current rendering exactly (covered by existing Playwright e2e tests).

## Task Breakdown Preview

- 001 — `/api/public/store-brand/` endpoint + accent validation + cache header + tests
- 002 — `fetchStoreBrand()` SSR helper + types + unit tests
- 003 — Booking page (`app/page.tsx`) consumes the helper; logo + accent render branded data
- 004 — QR page (`app/qr/[slug]/page.tsx`) refactor onto the helper (behaviour-preserving)

## Dependencies

- Hard: `one-qr` (in main) — `Store.brand` field + the SSR-branding pattern to refactor against.
- Soft: none. Independent of other v5 slices.

## Success Criteria (Technical)

- `Store.brand = {"logo_url": "...", "accent": "oklch(75% 0.18 200)"}` changes the booking-page header on the next request, with no rebuild.
- `Store.brand = {}` produces unchanged rendering (Playwright e2e tests pass).
- The endpoint passes a `curl` test returning the right JSON; the validation test rejects `accent="javascript:..."` and similar.
- The existing 10-pass Playwright suite still passes (the QR refactor is behaviour-preserving).
- Lighthouse Performance on `/` does not drop by more than 2 points.

## Estimated Effort

- ~1 day total wall-time as a single agent. Critical path: 001 → 002 → {003, 004} in parallel.

## Tasks Created
- [ ] #138 - /api/public/store-brand/ endpoint + accent validation + tests (parallel: false)
- [ ] #139 - fetchStoreBrand() SSR helper + types + tests (parallel: false, depends on 001)
- [ ] #140 - Booking page consumes helper; renders branded logo + accent (parallel: true, depends on 002)
- [ ] #141 - QR page refactor onto the helper (behaviour-preserving) (parallel: true, depends on 002)

Total tasks: 4
Parallel tasks: 2
Sequential tasks: 2
