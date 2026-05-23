---
name: memberships
description: Turn the placeholder reward_points / total_visits counters into a real points ledger, tier system, and staff-mediated redemption flow — the "loyalty" surface COSReady advertises.
status: backlog
created: 2026-05-23T14:19:04Z
---

# PRD: memberships

## Executive Summary

The v3 retention slice gave PlayDesk a `Customer` with a `total_visits` counter (`backend/core/models.py:122`), and the v3 one-qr slice gave it a `QRAction.reward_points` field (`backend/core/models.py:188`) — but neither of these is a real loyalty signal today. `total_visits` is a counter no one earns *anything* from; `reward_points` is a number printed on a chip with no balance to credit. The "+10 pts" feedback in the one-qr PRD's customer story is a UI placeholder, not a transaction.

This epic turns those placeholders into a working membership module: a points ledger (every earn / spend is one row), a redeemable-reward catalogue, a small tier system that reads off the customer's lifetime points, and an admin surface that lets staff view a customer's balance, adjust it manually with an audit reason, and process a redemption. Earn signals wire into the two already-shipped surfaces (booking completion + identified QR clicks). The customer-facing portal is deliberately out of scope — staff-mediated only in v4.

## Problem Statement

COSReady's public site names "memberships and rewards" as one of its core modules. PlayDesk's current state:

- A customer with 12 bookings sees `total_visits = 12` in admin and nothing else.
- A QR click on an action worth `reward_points = 10` records a `QREvent` row and never credits the customer with anything.
- Staff have no way to say "this customer redeemed a free hour", because there is no balance to debit.
- There is no tier ("gold / silver"), so there's nothing to perks-based pricing or messaging branching could key off.

Without a points ledger, every loyalty story — earn, redeem, tier upgrade, expiry, audit — is structurally impossible.

## User Stories

- **As a customer**, when I complete a booking I earn a configurable number of points (default 10), and when I tap a QR action worth points my account gets credited.
  - *Acceptance:* completing a booking writes one `+10` row to my ledger; tapping a QR chip with `reward_points = 20` while my cookie identifies me writes one `+20` row. My current balance is the sum of all rows.
- **As staff**, I can open a customer's profile and see their current balance, their current tier, the last 20 ledger entries with timestamps + source, and a "redeem" dropdown of rewards they can afford.
  - *Acceptance:* the balance shown matches `SUM(delta)`; the redeem dropdown only lists rewards whose `cost_points <= balance`; choosing one writes a `-cost` row + a `Redemption` row in a single transaction.
- **As staff**, I can manually adjust a customer's balance (positive or negative) with a required reason, and the adjustment shows up in the ledger attributed to me.
  - *Acceptance:* the adjust form requires a non-empty reason; the resulting ledger row has `source = "adjustment"`, `reference = reason text`, `author = staff user`.
- **As a store owner**, I can configure the reward catalogue (`/admin/rewards`) and the tier thresholds (`/admin/tiers`) without touching code.
  - *Acceptance:* CRUD endpoints exist; changes are reflected on the next customer-detail render; tier thresholds are integers and `tier(balance)` returns the highest tier where `balance >= threshold`.
- **As a customer (visiting the QR page with my cookie set)**, my current tier badge is visible on the chip header so the loyalty mechanic feels real, not theoretical.
  - *Acceptance:* the SSR'd QR page reads the `pd_customer` cookie, looks up the tier, and renders the tier name + small icon in the page header. Anonymous visitors see no tier strip.

## Functional Requirements

1. **`PointTransaction` model** (single source of truth — every earn or spend is one immutable row):
   - `customer (FK)`, `delta (int, +/-)`, `source ('booking' | 'qr_click' | 'redemption' | 'adjustment' | 'backfill')`, `reference (str, free-text or FK-id-as-string for traceability)`, `author (User FK, nullable)`, `created_at`, `balance_after (int, denormalised for fast lookup on the customer detail page)`.
2. **`Reward` model**: `store (FK)`, `name`, `description`, `cost_points (int, > 0)`, `enabled (bool, default True)`, `created_at`. No global rewards in v4; per-store only.
3. **`Redemption` model**: `customer (FK)`, `reward (FK)`, `transaction (FK to PointTransaction)`, `staff (User FK)`, `redeemed_at`. One row per redemption; the FK to the debit transaction is what makes the audit trail bidirectional.
4. **`RewardTier` model**: `store (FK)`, `name (e.g. "Silver", "Gold")`, `min_lifetime_points (int)`, `perks_text (free-form, displayed on customer detail)`, `position (int, sort order)`. Unique on `(store, position)`.
5. **`award_points(customer, delta, source, reference, author=None)` helper** — the *only* code path that writes to `PointTransaction`. Reads the latest row's `balance_after`, computes the new balance, writes the new row. Atomic via `select_for_update` on the customer row.
6. **Earn signals**:
   - Booking signal: when a `Booking` transitions to `status = "completed"`, call `award_points(customer, store.points_per_booking, "booking", str(booking.id))`. `points_per_booking` is a new `Store` field (default 10).
   - QR click hook: in the existing `POST /api/qr/event/` view, after recording the `QREvent`, if `customer_id` is non-null and `action.reward_points > 0`, call `award_points(customer, action.reward_points, "qr_click", str(event.id))`.
7. **Redemption flow** — `POST /api/admin/customers/{id}/redeem/` with body `{ reward_id }`:
   - Atomic: lock customer row, verify `balance >= reward.cost_points`, write `-cost` transaction with `source = "redemption"`, create `Redemption` row, return updated balance.
   - 409 with `{"error":"insufficient_points","balance":N,"cost":M}` if the check fails.
8. **Adjustment endpoint** — `POST /api/admin/customers/{id}/adjust-points/` with body `{ delta, reason }`. Writes one transaction with `source = "adjustment"`, `reference = reason`, `author = request.user`. Reason is required and non-empty.
9. **Membership-view endpoint** — `GET /api/admin/customers/{id}/membership/` returns `{ balance, tier, next_tier, points_to_next_tier, recent_transactions: [20], available_rewards: [...] }`. Single fetch powers the detail-page section.
10. **Tier resolver** — `core.memberships.tier_for(customer) -> RewardTier | None`. Reads `customer.lifetime_points_earned` (sum of positive deltas across all transactions, NOT current balance), returns the tier with the highest `min_lifetime_points <= lifetime_earned`.
11. **Admin reward/tier CRUD** — `GET/POST/PATCH/DELETE /api/admin/rewards/`, `/api/admin/tiers/`.
12. **Backfill data migration** — for each existing `Customer`, write one `backfill` PointTransaction crediting `total_visits * default_points_per_visit` (10). Idempotent: skipped if the customer already has any transactions.
13. **Customer-detail frontend section** — new "Membership" card on `/admin/customers/[id]`: balance (large), tier badge + perks text, "Adjust" button (modal), "Redeem" dropdown, recent-transactions table.
14. **Admin pages** — `/admin/rewards` (CRUD list), `/admin/tiers` (CRUD list).
15. **Public tier badge** — `frontend/src/app/qr/[slug]/page.tsx` reads the `pd_customer` cookie server-side, looks up the tier, and renders a small badge in the page header. Anonymous visitors see no badge (no-op render).

## Non-Functional Requirements

- `award_points` must be safe under concurrent calls: two simultaneous booking-completions on the same customer must serialise via `select_for_update` so the denormalised `balance_after` never disagrees with `SUM(delta)`.
- A consistency check `SUM(delta) == latest.balance_after` is exposed as a management command (`python manage.py memberships_check`) and run in CI on a seeded dataset.
- The membership endpoint returns in <150ms for a customer with 10 000 historical transactions (one indexed lookup for the latest row, one indexed range scan for the 20 most recent).
- Backfill is reversible (delete `PointTransaction` rows with `source = "backfill"`).
- The redeem flow has no partial-state failure mode — either both rows write or neither does.

## Success Criteria

- A reviewer can: complete a seeded booking → see `+10 pts` on the customer's detail page; tap a QR chip worth 20 points while their cookie is set → see `+20 pts`; redeem a 25-point reward → see balance drop, transaction logged, redemption row created.
- `SUM(delta)` over all transactions for any customer equals their displayed balance (verified by `memberships_check`).
- Tier resolver is correct for empty-balance, edge-of-threshold, and beyond-top-tier customers (covered by ≥5 unit tests).
- No regression in the existing backend test suite after the backfill.
- The public QR page shows the right tier badge to identified visitors and no badge to anonymous visitors.

## Constraints & Assumptions

- Points are *per-store* — a customer earning 100 points at store A does not see them at store B (matches the existing per-store `Customer` uniqueness from retention).
- Points do not expire in v4 (called out in Out of Scope below).
- Tiers are read-only from a customer's perspective — no manual tier overrides. The tier is always a deterministic function of `lifetime_points_earned`.
- The reward catalogue is small enough (<100 rewards per store) that no search / pagination is needed in v4.
- Staff-mediated redemption only. A customer cannot self-redeem in v4.

## Out of Scope

- Customer-facing self-service portal ("log in to see my points / redeem rewards").
- Point expiry policies (e.g. "points expire after 12 months").
- Cross-store points roll-up.
- Tier-based discounts at checkout (Stripe coupon integration).
- Push / SMS notification when a customer crosses a tier threshold (would be the `outbound` slice's job).
- Marketing-driven point campaigns ("2× points this weekend") — covered by a future `campaigns` × `memberships` combo.

## Dependencies

- Hard: `retention` (already in main) — depends on the `Customer` model and `Customer.total_visits` for the backfill.
- Soft: `one-qr` (already in main) — the click hook is additive; if one-qr were absent the booking-completion earn path would still work.
- Soft: `outbound` (parallel v4 slice) — tier-crossing notifications would route through outbound, but are explicitly out of scope here.
- Soft: `campaigns` (parallel v4 slice) — points can be a segmentation signal ("customers with >100 lifetime points"), but campaigns does not depend on memberships shipping first.
