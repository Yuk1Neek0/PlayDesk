---
name: billing-payments
description: Stripe integration for booking deposits, completion charges, and cancellation refunds. Wires payment_intent_id + payment_status onto Booking, exposes a webhook receiver, surfaces a refund action in the admin booking detail, and emails customers receipts. Per-store Stripe account so chain owners get separate payouts.
status: backlog
created: 2026-05-24T00:00:00Z
---

# PRD: billing-payments

## Executive Summary

PlayDesk has shipped 16 epics covering the entire reservation, agent, RAG, multi-channel, multi-location, memberships, outbound, dashboard, and branded-booking surface — but every booking ends with `confirmed` and zero money has changed hands. Stores are running on the honor system + in-person cash/card at session start. This blocks two real use cases: (a) deposits to deter no-shows, and (b) full prepayment for premium / package bookings.

This epic ships Stripe integration: each store can connect a Stripe account (Stripe Connect, standard onboarding); booking-create optionally charges a deposit (per-store-configurable %); on session completion staff can charge the remaining balance with one click; cancellations within the policy window auto-refund per a configurable matrix; webhook-driven payment-status updates land on the `Booking` row; customers get email + SMS receipts.

It consumes v8's `total_amount` as the source of truth for *what* to charge, and v6's store context for *which* Stripe account to charge to. It deliberately ships no in-portal payment-method management (one-shot charges from the booking page only).

## Problem Statement

Bookings are confirmation-only. Concretely:

- A customer books a $200 4-hour PS5 package, never shows up. Store loses the slot. No deposit was held, no card was on file.
- A customer prepays in person — staff records it informally; no audit trail tied to the `Booking` row; reconciliation at month-end is a spreadsheet exercise.
- A chain owner running 2 stores has zero way to see "how much revenue per store this month" — the business-dashboard (v5) shows booking *counts*, not money, because money isn't in the system.
- Cancellation policy (v7 `cancellation_lead_hours`) is enforced — but with no payment, "free cancellation" is meaningless. The policy needs teeth.

Real game lounges fall into two camps: those that take a deposit at booking + collect the rest in person (deposit model), and those that take full prepayment for prime-time / weekend slots (prepay model). PlayDesk needs to support both, configurable per store + per resource.

## User Stories

- **As a chain owner**, I navigate to admin Settings → Payments and connect my store's Stripe account via Stripe Connect onboarding. Each store has its own. After onboarding I see "Connected · acct_xxxx" and a status badge.
  - *Acceptance:* `Store.stripe_account_id` + `stripe_charges_enabled` populated by the OAuth return; onboarding link is generated per store.
- **As a chain owner**, I configure deposit policy per store: `deposit_mode = none | percentage | fixed`, `deposit_value` (e.g., 30%), and per-resource overrides for premium resources ("PS5 Pro Suite: 100% prepay").
- **As a customer**, my booking page shows the deposit amount required ("Pay $24.00 deposit now to confirm — balance $56.00 at the venue"), Stripe Elements card form inline; on submit, the booking is created in `pending_payment`, the charge succeeds, status flips to `confirmed` and I see "Booking confirmed, deposit captured" + an SMS confirmation.
  - *Acceptance:* booking row never reaches `confirmed` without a successful PaymentIntent (or `deposit_mode=none`); failed charge → booking row stays `pending_payment` for 10 min then auto-cancelled by a cron sweep.
- **As staff**, on the admin booking detail I see "Deposit: $24.00 captured · Balance: $56.00 due" with a "Charge balance" button. Click → enter card or "use card on file" → Stripe charge → balance shows 0 due, badge flips to "Paid in full".
- **As a customer**, when I cancel via the v7 portal within the policy window, the deposit refunds automatically per the per-store refund matrix (e.g., > 48h: 100% refund, 24–48h: 50%, < 24h: 0%). I get an SMS: "Refund of $24.00 issued to your card ending 4242".
- **As a chain owner**, on the v5 business dashboard, I see "Revenue this month: $4,820" (sum of captured payments) broken out by store, plus a row "Refunds: $180".
- **As a developer**, Stripe webhooks land at `POST /api/stripe/webhook/`; signature is verified; events update `Booking.payment_status` + `Payment` rows; idempotent (Stripe retries are no-ops via `Payment.stripe_event_id` unique constraint).

## Functional Requirements

1. **`Payment` model** in a new `billing` app:
   - `store` (FK), `booking` (FK), `kind` (deposit | balance | refund | adjustment), `amount` (Decimal, signed for refunds), `currency` (3-letter), `status` (pending | succeeded | failed | refunded), `stripe_payment_intent_id`, `stripe_charge_id`, `stripe_event_id` (unique-or-null), `created_at`, `metadata` (JSONField).
2. **`Booking` augmentation**:
   - `payment_status` (choices): `not_required` | `pending_payment` | `deposit_paid` | `paid_in_full` | `refunded` | `partially_refunded`.
   - `deposit_amount: Decimal` (frozen at booking time).
   - `balance_amount: Decimal` (computed: `total_amount - deposit_amount`).
   - `payment_intent_id`: convenience pointer to the *initial* deposit intent.
3. **`Store` augmentation**:
   - `stripe_account_id` (str, nullable), `stripe_charges_enabled` (bool, default false), `currency` (3-letter, default "USD").
   - `deposit_mode` (none | percentage | fixed), `deposit_value` (Decimal).
   - `refund_matrix` (JSONField): `[{"min_hours": 48, "refund_pct": 100}, {"min_hours": 24, "refund_pct": 50}, {"min_hours": 0, "refund_pct": 0}]` — evaluated as "find first row where now+min_hours <= booking.start_at".
4. **`Resource` augmentation**:
   - `deposit_override_mode` (null | none | percentage | fixed), `deposit_override_value` (Decimal, nullable). Null → use store default.
5. **Stripe Connect onboarding flow**:
   - `POST /api/admin/stripe/connect/` → returns Stripe onboarding URL for `request.store`; creates a Stripe Connect Standard account if `stripe_account_id` is null; persists the id.
   - Stripe redirect lands at `/admin/settings/payments/return?store=<slug>` → backend calls `Account.retrieve()` to update `stripe_charges_enabled`.
   - Admin page at `/admin/settings/payments/` shows status + reconnect link.
6. **Deposit calc helper**:
   - `billing.calc_deposit(store, resource, total_amount) -> Decimal` — applies resource override if set else store default; floors at 0, caps at total.
7. **Booking-create wiring**:
   - When `deposit_mode != none`: booking row created with `payment_status='pending_payment'`; PaymentIntent created with `transfer_data[destination] = store.stripe_account_id` (application_fee_amount = 0 for v9 — platform-fee logic out of scope).
   - Frontend Stripe Elements confirms the PaymentIntent; webhook receipt flips `payment_status='deposit_paid'`; booking status → `confirmed`.
   - When `deposit_mode == none`: booking row created with `payment_status='not_required'`, `status='confirmed'` immediately.
8. **Charge-balance endpoint** — `POST /api/admin/bookings/{id}/charge-balance/`:
   - Creates a new PaymentIntent for `balance_amount`; uses saved card if `setup_for_off_session` was set (out of scope: card-on-file flow → staff must collect card details inline or customer pays via a tokenized link).
   - **v9 simplification**: charge-balance generates a one-time Stripe Checkout link; admin sees "Send link to customer" → SMS / WhatsApp delivery via v4 outbound. Customer pays via Stripe-hosted page. Webhook updates booking.
9. **Cancellation + refund**:
   - When customer (v7 portal) or staff cancels: backend reads `Store.refund_matrix`, computes refund_pct, calls Stripe `Refund.create(payment_intent=…, amount=…)`.
   - Booking row: `payment_status='refunded' | 'partially_refunded'`; `Payment` row created with negative amount + `kind='refund'`.
   - SMS notification template `booking_refunded` (template lives in v4 outbound).
10. **Webhook receiver** — `POST /api/stripe/webhook/`:
    - Verifies `Stripe-Signature` header against `STRIPE_WEBHOOK_SECRET`.
    - Handles: `payment_intent.succeeded`, `payment_intent.payment_failed`, `charge.refunded`, `account.updated` (charges_enabled toggle).
    - Idempotent via `Payment.stripe_event_id` unique constraint.
    - Returns 200 even on internal errors after persisting the raw event to `WebhookEvent` for retry; Stripe will retry on non-2xx.
11. **Sweep cron** — `python manage.py sweep_pending_payments` (run hourly): cancels bookings stuck in `pending_payment` for > 10 min, frees the slot.
12. **Receipt emails + SMS** — on `payment_intent.succeeded` + on refund, send the customer:
    - SMS via v4 outbound (templates: `payment_receipt`, `refund_receipt`).
    - Email (new — minimal SendGrid or SMTP integration; falls back to log-only if `EMAIL_BACKEND` is console).
13. **Business-dashboard (v5) augmentation** — new tile "Revenue (MTD)" = `sum(Payment.amount where kind in (deposit,balance), succeeded, this month, store-scoped)`; new tile "Refunds (MTD)". Hooked into the existing v5 dashboard endpoint.
14. **Admin payment dashboard** at `/admin/payments/` — paginated list of Payment rows, store-scoped, filterable by status + date range.

## Non-Functional Requirements

- **Idempotency**: every webhook event recorded; replaying the same Stripe event is a no-op.
- **PCI scope**: card data never touches our backend. Stripe Elements (booking page) + Stripe Checkout (balance charge) keep us in SAQ-A territory.
- **Test mode**: settings flag `STRIPE_TEST_MODE=True` swaps to `sk_test_…` keys; CI runs entirely against Stripe test mode with the `stripe-cli` event-forwarding pattern (or, simpler, with the `stripe-mock` Docker image).
- **Atomicity**: booking-create + PaymentIntent-create are not atomic across DB + Stripe — we accept the order "row first, then intent" and the sweep handles the orphan window.
- **No backward-incompat**: existing bookings get `payment_status='not_required'` via migration; nothing on the existing surfaces breaks.

## Dependencies

- **v8 pricing-rules** (will ship in parallel) — reads `Booking.total_amount`. v9 ships before v8 merges? Then v9 uses `resource.hourly_rate * hours` and re-reads on v8 merge. Simpler: define an `effective_total(booking)` helper that v8 overrides.
- **v6 multi-location** (shipped) — `request.store` for routing all payment operations.
- **v4 outbound** (shipped) — SMS templates for receipts + refund notifications.
- **v5 business-dashboard** (shipped) — revenue tiles hook into the existing dashboard endpoint.
- **v7 customer-portal** (will ship in parallel) — cancellation flow lives in the portal. If v7 merges later, v9 ships the staff-side cancellation only; portal pickup is a 10-line follow-on.

## Out of Scope

- Card-on-file (saved cards for future bookings) — v10.
- Subscription billing / recurring memberships — separate scope.
- Multi-currency per store — single-currency per store.
- Tax calculation (sales tax / VAT / GST) — handled out-of-band by accounting.
- Platform fee / application_fee_amount on Stripe Connect — chain has no platform-fee revenue model yet.
- Payouts / payout-status surface — handled in Stripe Dashboard.
- Dispute / chargeback handling — handled in Stripe Dashboard, logged via webhook only.
- Apple Pay / Google Pay UI (Stripe Elements handles automatically with no extra work — included implicitly).

## Expected Conflict Zones with Peer Epics (v7, v8)

- `Booking` model: v8 adds `total_amount`, `rule_snapshot`, `refund_amount`. v9 adds `payment_status`, `deposit_amount`, `payment_intent_id`. Both additive — merge migration if numbers collide.
- Booking-create endpoint: v8 wraps it for quote freeze, v9 wraps it for PaymentIntent creation. Order matters — quote must compute first. Both agents should follow: "load booking row → compute total (v8) → create intent (v9) → return".
- Cancellation: v7 ships the customer-side cancel endpoint. v9 needs that endpoint to trigger refund logic. If v7 merges first, v9 patches the cancel handler to call refund. If v9 merges first, v9 ships the refund logic on the staff-side cancel; v7 wires it in on merge.
- `OutboundTemplate`: v9 adds `payment_receipt`, `refund_receipt`. v7 adds `booking_rescheduled`, `booking_cancelled`. Different rows.
- Settings: v9 adds `STRIPE_*` envs. v7 adds nothing. v8 adds nothing. No collision.
- Business-dashboard endpoint: v9 augments existing v5 endpoint. No peer touches it.
