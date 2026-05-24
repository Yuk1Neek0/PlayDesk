---
name: branded-booking
description: Per-store branding (logo + accent colour) on the customer-facing booking page, generalising the one-qr SSR-branding pattern to /book — closes the "branded booking" COSReady surface item.
status: backlog
created: 2026-05-24T01:00:22Z
---

# PRD: branded-booking

## Executive Summary

The v3 one-qr slice introduced `Store.brand` (JSONField with optional `logo_url` and `accent` keys) and an SSR-rendered branded page at `/qr/[slug]`. The customer booking page at `/` is the OTHER customer-facing surface — and it ships with PlayDesk's default branding regardless of which store the customer is booking with. COSReady's public site advertises "branded booking" specifically as a feature that lets each business present its own identity to its customers.

This epic surfaces `Store.brand` on the booking page header (logo + accent colour) using the exact same SSR-data-fetch pattern as `/qr/[slug]`. No URL change in v5 (the single-store assumption everywhere else stays — multi-location is v6). The branded surface comes from a single new SSR loader call to a small public endpoint.

## Problem Statement

A customer scanning a printed QR card sees the store's branding on `/qr/[slug]`; the SAME customer tapping "Book a session" lands on a page that says "PlayDesk Downtown · Toronto" with the default PlayDesk teal. The two surfaces feel disconnected. Worse, when this product is sold to a second store (the v6 multi-location prerequisite), every booking page would still look like PlayDesk's flagship.

The existing `Store.brand` JSON already supports the branding fields — they just aren't read on the booking page yet.

## User Stories

- **As a store owner**, my logo and accent colour show in the header of the customer booking page the same way they show on the QR landing page.
  - *Acceptance:* setting `Store.brand = {"logo_url": "https://…", "accent": "oklch(…)"}` is visible on `/` within one request, no rebuild needed.
- **As a customer**, the booking page header carries the same branding I just saw on the QR card I scanned to get here.
  - *Acceptance:* logo image renders, accent colour applies to the primary CTA buttons (Confirm booking, Pick slot).
- **As staff**, branding falls back gracefully — a store with `brand = {}` shows the default PlayDesk logo + accent (current behaviour preserved).
- **As a developer**, the branding loader is the same shape on `/` and `/qr/[slug]` — one helper, two callers.

## Functional Requirements

1. **Public store-branding endpoint** `GET /api/public/store-brand/` (no auth, single-store assumption: returns the default store's brand). Response: `{ name, logo_url: str | null, accent: str | null }`.
2. **Shared SSR helper** `frontend/src/lib/store-brand.ts::fetchStoreBrand(): Promise<StoreBrand>` consumed by both `app/page.tsx` (booking) and `app/qr/[slug]/page.tsx` (QR). De-duplicates the brand fetch.
3. **Booking page** `frontend/src/app/page.tsx` reads brand SSR-side and:
   - Renders `<Image src={logo_url} ... />` in the header when `logo_url` is set; otherwise the existing default logo SVG.
   - Sets the accent CSS variable (`--pd-accent`) on the page wrapper to the `accent` value when present; otherwise the existing default.
4. **One QR page** `frontend/src/app/qr/[slug]/page.tsx` — refactored to use the same helper. No behaviour change.
5. **Default brand fallback** — `Store.brand` may be `{}`, `{logo_url}`, `{accent}`, or both. Frontend handles all four shapes.
6. **Accent value safety** — the endpoint validates `accent` is a CSS-safe oklch / hex / rgb string before returning it; invalid → return `null`. Prevents an admin typo from breaking the page.

## Non-Functional Requirements

- One additional public endpoint, no auth, served from cache (`Cache-Control: public, max-age=60`) because brand changes are rare and the booking page hits it on every render.
- SSR fetch must add no measurable latency to first-paint — the brand fetch is in parallel with whatever else `/` loads SSR-side.
- No JavaScript on `/` runs differently for a branded vs. unbranded store — branding is purely CSS-variable + logo-image substitution.
- `prefers-reduced-motion` and existing accessibility behaviours unchanged.
- No database migration — `Store.brand` already exists.

## Success Criteria

- Setting `Store.brand = {"logo_url": "https://example.com/logo.png", "accent": "oklch(75% 0.18 200)"}` on the demo store changes the `/` header logo and the Confirm-booking button colour on the next request.
- Setting `Store.brand = {}` leaves the existing default appearance unchanged.
- The QR page refactor preserves its current rendering (Playwright e2e tests pass unchanged).
- Lighthouse score on `/` does not regress by more than 2 points.

## Constraints & Assumptions

- Single-store assumption holds — the public endpoint returns the default store. Multi-location URL routing (`/book/[slug]`) is explicitly deferred to v6.
- `accent` is constrained to a tiny CSS-value grammar (oklch / hex / rgb) — no arbitrary CSS.
- Logo image is loaded directly from `Store.brand.logo_url` (assumed already hosted somewhere CDN-cached); PlayDesk does not host customer-uploaded images in v5.

## Out of Scope

- Multi-location URL routing (`/book/[slug]`) — v6.
- Customer-uploaded logo via the admin (the URL is set by hand via Django admin for v5).
- Custom CSS / fonts per store beyond logo + accent.
- A favicon swap per store.
- Email template branding (would belong with a future email outbound channel).

## Dependencies

- Hard: `one-qr` (in main) — `Store.brand` field + the `/qr/[slug]` SSR-branding pattern to refactor against.
- Soft: none. Independent of other v5 slices.
