---
name: one-qr
description: Per-store branded QR landing page with configurable action chips and per-action reward points — the most distinctive feature on COSReady's public site.
status: backlog
created: 2026-05-23T04:27:55Z
---

# PRD: one-qr

## Executive Summary

COSReady's One QR feature is the most distinctive product surface on their public site: a single QR code links to a branded customer-facing page where customers tap chips to leave a Google review, follow Instagram / TikTok / RedNote, add WeChat, connect to store WiFi, or any other configurable action — and earn reward points per action. PlayDesk doesn't have anything in this shape today.

This epic adds the One QR module end to end: a `QRAction` model so staff can configure actions per store, a public `/qr/[store-slug]` landing page that renders the chips with store branding, click tracking, and a small analytics endpoint that powers a "scans / clicks / engagement rate" admin card.

## Problem Statement

Beauty and wellness businesses get most of their growth from in-person moments — the customer is at the front desk, the staff has 30 seconds. A printed QR card is the cheapest way to ask for a review, a follow, a WiFi handshake. But it has to be one QR, not five, and it has to be measurable. Today PlayDesk has no answer to "show me what the customer should tap when they walk in".

## User Stories

- **As a store owner**, I can configure a list of customer actions (review, Instagram, etc.), reorder them, and set a reward-points value per action, then print the QR.
  - *Acceptance:* the QR scans to a page showing exactly the configured actions in the configured order; reordering in admin is reflected on the public page within the next request.
- **As a customer**, I scan the QR with my phone, see the store's branded landing page in my language, tap a chip ("Leave a Google review"), get redirected to the target URL, and on return see "+10 pts" feedback.
  - *Acceptance:* the page loads in <1.5s on a mid-tier phone, the redirect logs a click event, and the points feedback shows even on first-time customers (anonymous events).
- **As staff**, on `/admin/qr` I see a card row with total scans, total clicks, engagement rate, and a per-action breakdown for the last 7 / 30 / 90 days.
  - *Acceptance:* the analytics card row reflects today's events within one minute.

## Functional Requirements

1. **`QRAction` model**: `store_id (FK)`, `kind ('review' | 'instagram' | 'tiktok' | 'rednote' | 'wechat' | 'wifi' | 'custom')`, `label`, `target_url`, `position (int)`, `reward_points (int default 0)`, `enabled (bool)`. Unique on `(store_id, position)` for stable ordering.
2. **`QREvent` model** for analytics: `action_id (FK, nullable for scan events)`, `customer_id (FK, nullable)`, `kind ('scan' | 'click')`, `created_at`, `user_agent`, `locale`.
3. **Admin endpoints**:
   - `GET/POST /api/admin/qr-actions/` — list / create
   - `PATCH /api/admin/qr-actions/{id}/` — edit / reorder (accepts `position`)
   - `DELETE /api/admin/qr-actions/{id}/`
   - `GET /api/admin/qr-analytics/?days=7` — aggregates: total scans, total clicks, engagement rate, per-action breakdown
4. **Admin config page** `/admin/qr`:
   - Drag-and-drop reorderable list of actions (HTML5 native drag-and-drop or react-dnd).
   - Inline edit of label / URL / points.
   - "Preview" button opens the public page in a new tab.
   - Top-of-page card row mirroring `/admin` style: scans, clicks, engagement rate.
5. **Public landing page** `/qr/[store-slug]`:
   - Server-rendered for speed (Next.js `app/qr/[slug]/page.tsx`).
   - Store branding from `Store.metadata.brand` (logo URL, accent colour override).
   - Chip grid with action icons, labels, optional point label.
   - On scan: fires a `scan` event before rendering (via a small server action).
   - On chip tap: client-side fires a `click` event, then `window.location = target_url`.
   - Bilingual rendering: respects `?lang=zh` or `Accept-Language`.
6. **Click tracking endpoint** `POST /api/qr/event/`: accepts `{ store_slug, action_id?, kind }`, records `QREvent`. Records `customer_id` if the request carries a `pd_customer` cookie set after any prior booking — otherwise anonymous.
7. **Default action set** — seed migration inserts a sensible 4-action defaults for the demo store (review, Instagram, WeChat, WiFi).

## Non-Functional Requirements

- Public page must hit the network only once on first paint — actions list, branding, and event-firing in a single SSR-rendered response.
- Anonymous event recording must not 401 / 403; identity is opportunistic.
- Click events are fire-and-forget — never block the redirect on the network call.
- `prefers-reduced-motion` honoured (chip enter animation cross-fades only).
- The admin drag-and-drop is keyboard-accessible (Tab + arrow-key reorder).

## Success Criteria

- A reviewer can scan a printed QR from the demo store, land on the page, tap "Leave a Google review", arrive at Google's review URL, and within a minute see the click on `/admin/qr`.
- Reordering in admin is reflected on the public page on the next render.
- Per-action breakdown sums to the total click count.
- Anonymous events outnumber identified events in seeded test data, proving the cookie path is non-blocking.

## Constraints & Assumptions

- Store slug is derived from `Store.name` (`slugify`) and stored on the model so the public URL stays stable.
- All target URLs are absolute http(s) URLs validated on save.
- No A/B testing of action sets in v3.
- Customer linkage is opportunistic via cookie — no login flow.

## Out of Scope

- A customer-facing portal showing accumulated points.
- Loyalty tiers / redemption flow (covered by a future memberships slice).
- A/B variants of the QR page.
- Custom CSS per store beyond logo + accent colour.

## Dependencies

- Soft: `retention` — when `Customer` exists, clicks can earn points against the customer profile. Without `retention`, events are anonymous and points are recorded on the event row only.
- No dependencies on `multi-channel`.
