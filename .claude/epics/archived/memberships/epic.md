---
name: memberships
status: completed
created: 2026-05-23T14:19:04Z
updated: 2026-05-23T16:43:38Z
progress: 100%
prd: .claude/prds/memberships.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/105
---

# Epic: memberships

## Overview

Add `PointTransaction`, `Reward`, `Redemption`, and `RewardTier` models plus a single `award_points()` helper that's the only writer of ledger rows. Wire earn signals to the two already-shipped surfaces (booking completion + identified QR clicks), backfill from `Customer.total_visits`, and ship the staff-mediated balance / redemption UI on the existing customer detail page. Public surface is one small tier-badge addition to the SSR'd QR landing page.

## Architecture Decisions

- **Append-only ledger, never an updated `Customer.points_balance` column.** Current balance is `balance_after` on the latest `PointTransaction` row (denormalised for fast read), but the source of truth is `SUM(delta)`. A `memberships_check` management command asserts the two agree on a seeded dataset; CI runs it.
- **One write path: `award_points()`.** Bookings, QR clicks, redemptions, and staff adjustments all funnel through this helper. Concurrency-safe via `select_for_update` on the customer row — two simultaneous earn events for the same customer serialise correctly.
- **Tier is a pure function of `lifetime_points_earned`, not current balance.** Redeeming points does not downgrade your tier. Computed at render time via `tier_for(customer)`; never persisted.
- **Backfill is reversible and idempotent.** A single data migration writes one `source = "backfill"` transaction per existing customer, but only if they have zero transactions today — re-running the migration is a no-op.
- **Staff-mediated redemption only in v4.** No customer-facing portal. The single concession to a customer-facing surface is the tier badge on the public QR page, which is read-only.

## Technical Approach

### Frontend Components
- `frontend/src/app/admin/customers/[id]/page.tsx` — extend with a new "Membership" card (balance large, tier badge, perks text, "Adjust" button, "Redeem" dropdown, last-20 transactions table).
- `frontend/src/components/admin/membership-section.tsx` — the card body, including the adjust + redeem modals.
- `frontend/src/app/admin/rewards/page.tsx` — CRUD list for per-store rewards.
- `frontend/src/app/admin/tiers/page.tsx` — CRUD list for per-store tiers.
- `frontend/src/app/qr/[slug]/page.tsx` — add a small SSR-rendered tier badge in the header when the `pd_customer` cookie resolves to an identified customer.
- Reuse the existing `pd-*` design tokens — no new CSS file.

### Backend Services
- `backend/core/migrations/000Z_memberships.py` — adds `PointTransaction`, `Reward`, `Redemption`, `RewardTier`, plus `Store.points_per_booking (int default 10)`.
- `backend/core/migrations/000ZZ_backfill_points.py` — data migration crediting `total_visits * points_per_booking` per existing customer (idempotent).
- `backend/core/models.py` — extends with the four new models.
- `backend/core/memberships.py` (new module):
  - `award_points(customer, delta, source, reference, author=None)` — the single ledger-write entry point.
  - `tier_for(customer) -> RewardTier | None` — pure function over lifetime earned.
  - `lifetime_points_earned(customer) -> int` — `SUM(delta) WHERE delta > 0`.
- `backend/core/signals.py` — extend with a `Booking` `post_save` that awards points on transition to `status = "completed"`.
- `backend/api/views_qr.py` — extend the existing QR event view: after recording an identified `QREvent`, call `award_points` for non-zero `reward_points`.
- `backend/api/views_memberships.py` (new):
  - `GET /api/admin/customers/{id}/membership/` — composite read.
  - `POST /api/admin/customers/{id}/adjust-points/` — staff adjustment with required `reason`.
  - `POST /api/admin/customers/{id}/redeem/` — atomic balance check + debit + `Redemption` write.
  - Standard DRF ModelViewSets for `/api/admin/rewards/` and `/api/admin/tiers/`.
- `backend/manage.py` command `memberships_check` — asserts `SUM(delta) == latest.balance_after` for every customer.

### Infrastructure
- No new dependencies.
- No env-var changes.

## Implementation Strategy

Schema first, then the ledger helper + invariants test, then earn signals + backfill, then the redemption / adjustment endpoints, then the frontend in parallel with the public tier badge. Backfill runs after the helper lands so it can call `award_points` rather than reimplementing the ledger write.

## Task Breakdown Preview

- 001 — Migration: PointTransaction + Reward + Redemption + RewardTier + Store.points_per_booking
- 002 — `award_points()` helper + `tier_for()` + `memberships_check` command + ledger invariants tests
- 003 — Earn signals: booking-completion + identified QR-click hook
- 004 — Backfill data migration from `Customer.total_visits` (idempotent)
- 005 — Admin endpoints: membership view, adjust-points, redeem, rewards CRUD, tiers CRUD
- 006 — Admin frontend: Membership card on customer detail + /admin/rewards + /admin/tiers + public QR tier badge

## Dependencies

- Hard: `retention` (in main) — `Customer`, `Customer.total_visits`, `core.phone.normalize_phone`.
- Hard: `one-qr` (in main) — `QRAction.reward_points`, the QR event view, the SSR'd QR page.
- Soft: `outbound` (parallel v4) — tier-crossing notifications would route through outbound; not in scope here.
- Soft: `campaigns` (parallel v4) — memberships data may inform segmentation later; not a v4 dependency.

## Success Criteria (Technical)

- Migration applies clean forward + reverse; backfill is idempotent and reversible.
- `award_points` is safe under concurrent calls (covered by a multi-thread test using `select_for_update`).
- `memberships_check` reports zero discrepancies on a seeded dataset of 100 customers with mixed earn/redeem histories.
- Tier resolver passes ≥5 unit tests (empty-balance, exact-threshold, between-tiers, above-top-tier, no-tiers-configured).
- `/api/admin/customers/{id}/membership/` returns in <150ms for a customer with 10 000 historical transactions.
- Existing backend test suite passes; ≥10 new tests cover earn paths, redeem flow, adjustment, backfill idempotency, and the tier badge SSR.

## Estimated Effort

- ~3 days for one developer.
- Critical path: 001 (schema) → 002 (helper) → 004 (backfill) and 003 (signals). Then 005 / 006 in parallel.

## Tasks Created
- [ ] #106 - Migration: PointTransaction + Reward + Redemption + RewardTier + Store.points_per_booking (parallel: false)
- [ ] #107 - `award_points()` helper + `tier_for()` + `memberships_check` command (parallel: false, depends on 001)
- [ ] #108 - Earn signals: booking-completion + identified QR-click hook (parallel: true, depends on 002)
- [ ] #109 - Backfill data migration from `Customer.total_visits` (parallel: true, depends on 002)
- [ ] #110 - Admin endpoints: membership view, adjust-points, redeem, rewards/tiers CRUD (parallel: true, depends on 002)
- [ ] #111 - Admin frontend: Membership card + rewards + tiers + public QR tier badge (parallel: true, depends on 005)

Total tasks: 6
Parallel tasks: 4
Sequential tasks: 2
Estimated total effort: 24 hours
