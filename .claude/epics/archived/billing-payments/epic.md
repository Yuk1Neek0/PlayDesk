---
name: billing-payments
status: completed
created: 2026-05-24T04:00:00Z
updated: 2026-05-24T11:50:00Z
progress: 100%
prd: .claude/prds/billing-payments.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/178
---

# Epic: billing-payments

## Overview

Stripe Connect per store. Booking-create optionally charges a deposit via Stripe PaymentIntent + Stripe Elements; webhook receiver updates `Booking.payment_status` idempotently; staff can charge the remaining balance via a Stripe-hosted Checkout link sent over SMS/WhatsApp; cancellations within policy auto-refund per a store-configured refund matrix; SMS + email receipts; revenue tiles added to the v5 business dashboard.

One new Django app (`billing`), 4 new models (`Payment`, `WebhookEvent`, plus augmentations to `Store`, `Resource`, `Booking`), one webhook endpoint, one cron sweep, ~3 new admin pages.

## Architecture Decisions

- **Stripe Connect Standard, not Direct/Express.** Each store onboards its own Stripe account; payouts go directly to the store; PlayDesk never holds funds (PCI scope minimal, no money-transmitter licensing concern). Standard onboarding means Stripe handles KYC/AML — we just consume `account.updated` webhooks.
- **PaymentIntent for deposit, Checkout Session for balance.** Deposit at booking-create needs the inline-on-page UX (Stripe Elements) so we don't lose the customer mid-flow. Balance-charge is staff-initiated and the customer isn't at a keyboard — a Stripe-hosted Checkout link sent over SMS is the simpler path and avoids card-on-file complexity.
- **Idempotency via `Payment.stripe_event_id` unique constraint.** Stripe retries webhooks aggressively; the constraint plus a "raw event persisted to `WebhookEvent` table" pattern gives us at-least-once semantics with no business-logic re-execution.
- **No card-on-file in v9.** Card-on-file means `SetupIntent` + customer-vault management + retention policy. Out of scope; v10 candidate.
- **Sweep cron for pending-payment orphans.** PaymentIntent + Booking row aren't atomic across DB + Stripe. A booking stuck in `pending_payment` > 10 min gets auto-cancelled by an hourly cron. Releases the slot.
- **Email receipts via Django's email backend, not a new SendGrid integration.** If `EMAIL_BACKEND` is set, send. If it's the console backend (default in dev), log only. No new pip dep. Production deployment will configure SMTP or upgrade to Anymail later — but that's an infra decision, not a code one.
- **`Store.refund_matrix` is JSON, not a separate `RefundRule` table.** Lookup is a single dict-search; rules are read 100× more than they're written; flexibility for new dimensions later (e.g., per-resource matrices) without migration churn.
- **Test against `stripe-mock`, not live Stripe in CI.** Faster, deterministic, no API key required for the test suite. Live-mode smoke tests run manually against `sk_test_…` keys.

## Technical Approach

### Frontend Components
- `frontend/src/app/admin/settings/payments/page.tsx` (new) — Stripe Connect status + connect/reconnect link + deposit-mode + refund-matrix editor.
- `frontend/src/app/admin/payments/page.tsx` (new) — paginated `Payment` row ledger, store-scoped, filter by status + date.
- `frontend/src/app/admin/bookings/[id]/PaymentPanel.tsx` (new) — embedded in booking detail; shows deposit/balance/refund history + "Charge balance" button.
- `frontend/src/app/s/[slug]/book/BookingPage.tsx` — augment with inline Stripe Elements payment block when deposit required.
- `frontend/src/lib/stripe.ts` (new) — `@stripe/stripe-js` loader keyed by `STRIPE_PUBLISHABLE_KEY`.
- `frontend/src/app/admin/page.tsx` (v5 dashboard) — add Revenue MTD + Refunds MTD tiles.

### Backend Services
- `backend/billing/` (new Django app) — `models.py` (`Payment`, `WebhookEvent`), `stripe_client.py` (thin wrapper around the `stripe` SDK), `views.py` (Connect onboarding + webhook receiver + charge-balance + refund), `tasks.py` (sweep cron).
- `backend/core/migrations/000A_store_payment_fields.py` (new) — `Store.stripe_account_id`, `stripe_charges_enabled`, `currency`, `deposit_mode`, `deposit_value`, `refund_matrix`.
- `backend/core/migrations/000B_resource_deposit_override.py` (new) — `Resource.deposit_override_mode`, `deposit_override_value`.
- `backend/core/migrations/000C_booking_payment_fields.py` (new) — `Booking.payment_status`, `deposit_amount`, `payment_intent_id`.
- `backend/core/migrations/000D_backfill_booking_payment_status.py` (new) — existing bookings → `payment_status='not_required'`, `deposit_amount=0`.
- `backend/api/views_public.py` — booking-create wired to create a PaymentIntent when deposit required.
- `backend/api/views_admin.py` (or wherever) — cancel endpoint wires refund.
- `backend/api/views_metrics.py` (v5) — augment business-dashboard payload with `revenue_mtd` + `refunds_mtd`.
- `backend/config/settings.py` — add `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_TEST_MODE`.
- `backend/config/urls.py` — wire `/api/stripe/webhook/`, `/api/admin/stripe/connect/`, `/api/admin/bookings/{id}/charge-balance/`.

### Infrastructure
- New pip dep: `stripe` (Python SDK). New frontend dep: `@stripe/stripe-js` + `@stripe/react-stripe-js`.
- New env vars: `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_TEST_MODE`.
- `docker-compose.yml` — add `stripe-mock` service for CI/test.
- New Django app `billing` added to `INSTALLED_APPS`.
- 4 additive migrations across `core` + 1 initial in `billing`.

## Implementation Strategy

Sequential within the epic — payment flows have hard ordering constraints (Stripe account must exist before intents; intent must exist before webhook can resolve; webhook idempotency depends on the WebhookEvent table).

The order:
1. 179 (Stripe Connect onboarding) — must land first to give the rest something to charge to.
2. 180 (Store/Resource deposit fields + calc_deposit helper + refund matrix) — pure schema + helpers.
3. 181 (Payment model + Booking payment fields + WebhookEvent + migrations) — schema for the rest.
4. 182 (booking-create wiring + Stripe Elements on booking page) — first end-to-end charge flow.
5. 183 (webhook receiver + signature verification + idempotency) — completes the payment loop.
6. 184 (cancel → refund + charge-balance via Checkout link + sweep cron) — admin-side completion.
7. 185 (SMS + email receipts + dashboard tiles + admin payment ledger) — surfacing.

Single agent, ~60–90 min wall-time (more complex than v7/v8).

## Task Breakdown Preview

- 179 — Stripe Connect onboarding: `Store.stripe_*` fields + `POST /api/admin/stripe/connect/` + admin settings page + `account.updated` webhook stub
- 180 — Store + Resource deposit config fields + `Store.refund_matrix` + `billing.calc_deposit(store, resource, total)` helper + tests
- 181 — `Payment` + `WebhookEvent` models + `Booking.payment_status` + `deposit_amount` + `payment_intent_id` migrations + backfill
- 182 — Booking-create wired to create PaymentIntent on deposit-required path + Stripe Elements block on booking page + `pending_payment` flow
- 183 — `POST /api/stripe/webhook/`: signature verification, idempotency via WebhookEvent, handlers for `payment_intent.succeeded`/`failed`/`charge.refunded`/`account.updated`
- 184 — Cancel endpoint → refund per matrix + `POST /api/admin/bookings/{id}/charge-balance/` (Stripe Checkout link via SMS) + `sweep_pending_payments` management command
- 185 — SMS receipts via v4 outbound + email receipt scaffold + v5 dashboard Revenue/Refunds tiles + `/admin/payments/` ledger page

## Dependencies

- Hard: `multi-location` (v6, in main) — store-scoped Stripe account, request.store routing.
- Hard: `outbound` (v4, in main) — SMS receipts + charge-balance link delivery.
- Hard: `business-dashboard` (v5, in main) — revenue/refunds tiles extend its existing endpoint.
- Soft: `pricing-rules` (v8, parallel epic) — reads `Booking.total_amount` if v8 lands first; falls back to `resource.hourly_rate * hours` otherwise via an `effective_total(booking)` helper.
- Soft: `customer-portal` (v7, parallel epic) — customer-side cancel triggers refund. If v7 hasn't merged, v9 still ships the staff-side cancel-refund; v7 wires in on merge.

## Success Criteria (Technical)

- Existing backend test suite passes after migrations + backfill.
- New tests in `billing/tests/`: webhook signature verification, idempotency replay, refund-matrix lookup, calc_deposit math, PaymentIntent creation + state transitions.
- Sweep cron test: booking stuck in `pending_payment` for > 10 min is cancelled.
- Stripe Connect onboarding: end-to-end with `stripe-mock` returns expected `account.updated` event.
- e2e test against `stripe-mock`: booking page → Stripe Elements (mocked) → webhook → booking confirmed.
- Manual smoke test gate: real `sk_test_…` keys → create real Stripe test account → confirm flow against live Stripe test mode.
- v5 dashboard returns `revenue_mtd` + `refunds_mtd` correctly under multi-store filter.

## Estimated Effort

- Single agent, ~60–90 min wall-time. Most complex of the three v7/v8/v9 epics due to webhook + cron + cross-system idempotency.

## Tasks Created
- [ ] #179 - Stripe Connect onboarding + Store.stripe_* fields + admin settings page (parallel: false)
- [ ] #180 - Store/Resource deposit config + refund_matrix + calc_deposit helper (parallel: true, depends on 179)
- [ ] #181 - Payment + WebhookEvent models + Booking payment fields + migrations + backfill (parallel: true, depends on 179)
- [ ] #182 - Booking-create PaymentIntent flow + Stripe Elements on booking page (parallel: false, depends on 180, 181)
- [ ] #183 - Webhook receiver + signature verification + idempotency + event handlers (parallel: false, depends on 181, 182)
- [ ] #184 - Cancel→refund flow + charge-balance via Checkout link + sweep cron (parallel: false, depends on 183)
- [ ] #185 - SMS+email receipts + v5 dashboard revenue tiles + /admin/payments/ ledger (parallel: false, depends on 184)

Total tasks: 7
