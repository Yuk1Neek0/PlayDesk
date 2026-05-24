---
name: pricing-rules
description: Dynamic pricing engine — peak/off-peak time windows, day-of-week pricing, member-tier discounts, package deals. Replaces today's flat per-resource hourly rate with a rule-evaluation pipeline. Computed at quote time + frozen on the booking row.
status: backlog
created: 2026-05-24T00:00:00Z
---

# PRD: pricing-rules

## Executive Summary

PlayDesk's booking engine has charged a single flat rate per resource per hour since v1 (`Resource.hourly_rate`). Every real game lounge charges differently: peak vs off-peak, weekday vs weekend, member discounts, multi-hour packages ("3-hour PS5 block — 20% off"). Today this is impossible to express — the value gap with COSReady-website's pricing module is the single biggest revenue feature missing from PlayDesk.

This epic ships a pricing-rules engine: a small rule-eval pipeline that takes `(resource, start_at, end_at, customer)` and returns `{base_amount, line_items, total_amount}`. Rules are admin-configured (`PricingRule` table) and scoped to a store. The output is surfaced as a quote on the booking page and frozen on the `Booking` row at booking-creation time so historical reads stay deterministic.

It deliberately ships nothing payment-related (v9 billing-payments owns the actual charge). The output of pricing-rules is *the number v9 charges*.

## Problem Statement

Current flow: `Resource.hourly_rate` (a single `DecimalField`) is multiplied by hours = total. That's the only thing PlayDesk can express.

What real game lounges need:

- **Peak / off-peak**: weekdays before 6pm are 40% off; Friday+Saturday after 8pm is +20%.
- **Day-of-week**: Tuesday is "Cheap Tuesday" — flat $30/hour on PS5.
- **Member tiers** (v4 memberships): Gold tier gets 15% off all bookings; Platinum gets 25%.
- **Package deals**: bookings ≥ 3 hours get 20% off the total; bookings ≥ 5 hours get 30% off.
- **Time-bracket rates**: PS5 is $50/hour for the first 2 hours, $30/hour after.
- **Combinations**: member discount stacks with peak discount, but only one package deal applies, and "Cheap Tuesday" is non-stackable with member tier.

The agent's `check_availability` tool currently returns prices from `Resource.hourly_rate` — these become wrong as soon as any rule is in play. The booking quote endpoint returns the flat number. The admin UI has no concept of pricing rules.

Without this, the chain can't price-differentiate at all — every COSReady-website demo collapses on this feature.

## User Stories

- **As a store-chain owner**, I can configure pricing rules in admin: "Friday + Saturday after 8pm: +20% on all PS5 stations" — and the customer-facing booking page reflects that immediately.
  - *Acceptance:* admin pricing-rule manager at `/admin/pricing/`; rule applies on next quote fetch; existing bookings unchanged (frozen rate).
- **As a Gold-tier customer**, when I'm logged in (v7 portal) or recognized by cookie, my quote shows the 15% member discount as a line item: "Member discount (Gold): -$12.00".
  - *Acceptance:* quote endpoint accepts `customer_id` (optional, from cookie); applies tier discount if rule exists for the customer's tier.
- **As a customer booking 4 hours**, my quote shows "Package deal (≥3hr): -20%" as a line item.
- **As a developer**, adding a new rule type (e.g., "early-bird booking discount: booked > 7 days in advance") requires writing one `RuleStrategy` subclass + registering it. No core engine changes.
- **As a chain manager**, I see in the booking-list admin the *frozen* rate that was paid at booking time, not the current rate — so a rate change on Monday doesn't retroactively rewrite Sunday's bookings.

## Functional Requirements

1. **`PricingRule` model** in a new `pricing` app:
   - `store` (FK Store), `name`, `description`, `enabled` (bool), `priority` (int, lower = applied first), `stackable` (bool — if false, this rule excludes others marked non-stackable).
   - `rule_type` (choices): `peak_hours`, `day_of_week`, `member_tier`, `min_duration`, `bracket_rate`.
   - `params` (JSONField) — shape depends on `rule_type`. Examples:
     - peak_hours: `{"days": ["fri","sat"], "start_hour": 20, "end_hour": 24, "adjustment_pct": 20}`
     - member_tier: `{"tier_id": 3, "discount_pct": 15}`
     - min_duration: `{"min_hours": 3, "discount_pct": 20}`
     - bracket_rate: `{"resource_id": 5, "brackets": [{"max_hours": 2, "rate": 50}, {"max_hours": null, "rate": 30}]}`
   - `applies_to_resource` (FK Resource, nullable — null = all resources in store).
2. **Pricing engine** at `backend/pricing/engine.py`:
   - `compute_quote(resource, start_at, end_at, customer=None) -> Quote`
   - `Quote` dataclass: `base_amount`, `line_items: list[QuoteLineItem]`, `total_amount`, `rule_snapshot: list[dict]` (the rules that fired, with their params at this moment — serializable for booking freeze).
   - `QuoteLineItem`: `label`, `amount` (signed), `rule_id` (or null for base).
   - Algorithm:
     1. Start with `base = resource.hourly_rate * hours`.
     2. Load all enabled `PricingRule` rows for the store, ordered by priority.
     3. For each rule, ask its `RuleStrategy.applies(ctx) -> bool` and `RuleStrategy.compute(ctx, running_total) -> Decimal` (signed adjustment).
     4. Respect `stackable`: if a non-stackable rule fires, skip subsequent non-stackable rules.
     5. Floor `total_amount` at 0.
3. **Rule strategies** — one class per `rule_type` in `backend/pricing/strategies/`. ABC pattern with `applies` + `compute`. Registered in a `RULE_REGISTRY` dict keyed on rule_type. Adding a new type = new file + registry entry.
4. **Quote API** — `POST /api/quote/` body `{resource_id, start_at, end_at, customer_id?}` → returns Quote serialized. Public (no auth), store-scoped via middleware. Used by the booking page and the agent's `check_availability` tool.
5. **Booking creation freezes the quote**:
   - `Booking` gains `total_amount: Decimal`, `rule_snapshot: JSONField` (serialized line items + which rules fired).
   - Migration backfills existing bookings: `total_amount = resource.hourly_rate * hours`, `rule_snapshot = []`.
   - Booking-create endpoint calls `compute_quote(...)` internally and writes the result. The client can pass `expected_total_amount`; if it differs from the recomputed total (race: rule changed between quote and submit), return 409 with the new quote.
6. **Agent tool update** — `check_availability` returns the *quoted* price per slot (using `compute_quote` for that resource+slot+anonymous customer); `get_resource_details` returns the unadjusted `hourly_rate` plus "starting from" text.
7. **Admin pricing-rule manager** — `/admin/pricing/` page (Next.js):
   - List view: store-scoped table of rules with enable/disable toggle, priority drag-handle, edit/delete actions.
   - Edit form: dynamic form per `rule_type` (params change shape). Validation client-side + DRF serializer-side.
   - "Test this rule" sandbox: pick a resource + time + tier → see the quote breakdown without saving anything.
8. **Booking-detail UI updates** — admin booking detail + v7 customer portal upcoming-bookings list show `total_amount` instead of recomputing. v6 booking page shows the live quote with line items below the time picker.
9. **Cancellation refund logic placeholder** — `Booking.refund_amount` field added but always 0 in v8. v9 billing-payments will read it.

## Non-Functional Requirements

- **Performance**: `compute_quote` must complete in < 50ms for a store with up to 50 enabled rules. Use a single query to fetch all store rules, evaluate in Python.
- **Determinism**: same inputs → same output. Engine takes no `now()` dependency except where `start_at` is in the future (e.g., early-bird rules — out of scope).
- **Backward compat**: bookings created before this slice have `total_amount` backfilled and `rule_snapshot = []`. Quote API gracefully handles stores with zero rules (returns base only).
- **Decimal arithmetic** throughout — no floats. Round to 2 dp at the final total only.
- **All existing tests pass.** Booking-create tests pre-pricing get a "no rules configured" path that returns base price.

## Dependencies

- **v6 multi-location** (shipped) — rules are store-scoped; engine reads `request.store`.
- **v4 memberships** (shipped) — member_tier rule type reads from `RewardTier`.
- **v2 backend-core** (shipped) — `Resource`, `Booking`, `hourly_rate`.

## Out of Scope

- Promo codes (separate epic — needs code-redemption flow, fraud limits).
- Time-of-booking discounts ("book before Friday 5pm for 10% off") — easy to add post-v8 as a new strategy.
- Subscription / membership-included-hours ("Platinum gets 5 free hours/month").
- Per-customer custom pricing.
- Tax calculation.
- Refund partial-amount calc (placeholder field only; v9 owns the refund flow).
- Currency conversion (everything is store's local currency, single-currency per store).

## Expected Conflict Zones with Peer Epics (v7, v9)

- `Booking` model: v8 adds `total_amount`, `rule_snapshot`, `refund_amount`. v9 will add `payment_status`, `payment_intent_id`. Both additive, no conflict.
- Booking-create endpoint: v8 wraps it with `compute_quote(...)` + freezes. v9 will hook deposit-charge in afterwards. Should compose if v8 lands first.
- Booking serializer: v8 adds price fields. v9 adds payment fields. v7 reads both as opaque numbers.
- Migration ordering: v8 adds `pricing` app + 3 migrations. v7/v9 only add to `core`. No collision.
- `check_availability` tool: v8 changes its return shape. v7/v9 do not touch.
