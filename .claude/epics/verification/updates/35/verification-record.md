# Verification Record — Issue #35 (Stream D: enhancements)

Verified: 2026-05-22, against the live `docker compose` stack.
Dev plan sections: §2.1 evals, §2.2 Stripe, §2.3 slot suggestions, §2.4 bilingual.

## Acceptance criteria

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Eval harness replays curated set against the live agent, reports per-case + aggregate accuracy | ✅ PASS | `python -m evals.run_evals` replays all 15 curated cases through the live `AgentLoop` + `AnthropicClient`, prints per-case PASS/FAIL + aggregate accuracy, exits non-zero on failure. `evals/` unit tests 11/11 |
| 2 | Stripe deposit flow: create_booking → Checkout → webhook → confirmed | ⚠️ PARTIAL | Booking half ✅ (`create_booking` → `pending_payment` row). Webhook half ✅ — live `POST /api/webhooks/stripe/` with an HMAC-signed `checkout.session.completed` event → HTTP 200, booking flipped `pending_payment`→`confirmed`; bad signature → 400. **Live test-mode Checkout-session API call: BLOCKED-PENDING-KEYS** — `.env` still has placeholder `sk_test_...` |
| 3 | `expire_holds` expires `pending_payment` bookings after TTL | ✅ PASS | Created fresh + stale `pending_payment` + old `confirmed` bookings; `expire_holds` deleted only the stale hold (past the 10-min TTL); fresh hold and confirmed booking survived |
| 4 | `check_availability` returns `suggestions` when the slot is taken | ✅ PASS | Booked the only room for a window, re-requested it → `{"available":[], "suggestions":[2 nearby bookable windows]}` — correct shape |
| 5 | Bilingual retrieval (zh / en) | ✅ PASS | Live `AgentLoop`: English query retrieved only `lang=en` chunks + English reply; Chinese query retrieved only `lang=zh` chunks + Chinese reply |

**Result: 4 PASS, 1 PARTIAL, 0 FAIL.**

## Bugs found and fixed in-stream

Both in `backend/core/payments.py`, committed `7798810`. No shared files touched.

### BUG-35-1 — `create_checkout_session` crashed on a placeholder key
The empty-key guard checked only for an unset key, not for the truthy `.env`
placeholder `sk_test_...`. With the placeholder present it called Stripe and
raised `AuthenticationError`. **Fix:** added `_stripe_configured()` which treats
`...`-suffixed placeholder values as unconfigured, so session creation cleanly
no-ops (booking still made) when Stripe is not really set up.

### BUG-35-2 — webhook incompatible with stripe-python 15.x
`stripe.Webhook.construct_event` returns a `StripeObject`, which has no
`.get()`. The webhook view consumed the event as a mapping → `AttributeError`
/ HTTP 500 on every real delivery. The mocked unit tests passed a dict, so this
was invisible. **Fix:** `verify_webhook_event` now returns a plain dict via
`event.to_dict()`.

## Regression check

99 tests pass — `test_stripe` 10, `evals` 11, plus 78 across api / agent_tools /
booking / registry. `ruff check` + `ruff format` clean.

## Left for #36 (integration & sign-off)

- **BLOCKED-PENDING-KEYS** — the only outstanding criterion-2 step: a live
  test-mode Checkout session. Needs a real `sk_test_...` key in
  `epic-verification/.env`, then `docker compose up -d backend` and one
  `create_booking` call to confirm a hosted Checkout URL is returned. Every
  surrounding code path (booking creation, webhook signature verification,
  status transition, TTL expiry) is already verified.
- **Agent quality (NOT a Stream D bug)** — eval aggregate accuracy is
  non-deterministic (66.7–73.3%). Some `should_book` cases intermittently stop
  after `check_availability` without calling `create_booking`. The harness
  correctly reports this; the defect surface is `backend/agent/` (out of
  Stream D scope). Worth a follow-up issue.
- Mid-run, Docker Desktop's engine briefly dropped and auto-restarted all three
  containers; dev deps were reinstalled and results re-verified — no impact.
- This stream's `verification-record.md` / `progress.md` were authored by the
  parent agent — the background stream agent was blocked from creating files.
