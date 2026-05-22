---
issue: 35
started: 2026-05-22T13:04:00Z
last_sync: 2026-05-22T13:29:29Z
completion: 90%
---

# Issue #35 — Stream D: enhancements

Status: **verification complete** — 4 PASS, 1 PARTIAL, 0 FAIL.

- Criteria 1 (evals), 3 (expire_holds TTL), 4 (slot suggestions), 5
  (bilingual) all pass against the live stack.
- Criterion 2 (Stripe) PARTIAL: booking creation, webhook signature
  verification and the `pending_payment`→`confirmed` transition all verified
  live; only the test-mode Checkout-session API call is BLOCKED-PENDING-KEYS
  (placeholder `sk_test_...` still in `.env`).
- Two bugs fixed in-stream in `core/payments.py` (commit `7798810`):
  placeholder-key crash, and stripe-python 15.x webhook incompatibility.
- Regression: 99 tests pass, ruff clean.
- See `verification-record.md` for full evidence and the #36 follow-ups.
