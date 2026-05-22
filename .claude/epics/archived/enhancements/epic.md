---
name: enhancements
status: completed
created: 2026-05-21T19:51:40Z
progress: 100%
prd: .claude/prds/enhancements.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/23
---

# Epic: enhancements

## Overview

Add the four independent nice-to-have capabilities — evaluation harness, Stripe deposits, slot suggestions, bilingual retrieval. Each is its own conflict-free task; all four can run as parallel agents once `backend-core` is merged.

## Architecture Decisions

- **No schema changes.** Foundation reserved every hook: eval-case format, `Booking.status = pending_payment`, the `suggestions` field, `KnowledgeChunk.lang`. Enhancements only add behavior.
- **Independent tasks.** Eval, Stripe, slot suggestions, and bilingual touch disjoint code paths — four parallel agents.
- **Mocked externals.** Stripe and LLM calls mocked in tests; CI needs no secrets.

## Technical Approach

- **Eval harness** — labeled cases (per `docs/contracts/eval-format.md`) + a replay runner asserting tool use / booking outcome / on-topic reply; prints per-case + aggregate accuracy.
- **Stripe** — Checkout (test mode) on `create_booking`; webhook flips `pending_payment` → `confirmed`; periodic command expires stale holds.
- **Slot suggestions** — `check_availability` populates its `suggestions` field with nearby alternatives; the LLM relays them.
- **Bilingual** — language detection on the user message; filter RAG retrieval by `lang`; system prompt instructs reply language.

## Implementation Strategy

Four independent tasks → four parallel agents, after `backend-core` merges.

## Task Breakdown Preview

- **001** Evaluation harness — labeled set + replay runner + accuracy report.
- **002** Stripe sandbox — Checkout, webhook, expiry command.
- **003** Conflict-aware slot suggestions — `check_availability` alternatives.
- **004** Bilingual retrieval — language detection + `lang`-filtered retrieval.

## Dependencies

- The `backend-core` epic — agent loop, tools, RAG, booking flow.

## Success Criteria (Technical)

- Eval script reports aggregate accuracy; Stripe test payment confirms a booking; unavailable requests yield alternatives; Chinese queries answered in Chinese from `lang: zh` chunks.
- CI green.

## Estimated Effort

- ~14h total; ~4h wall-clock with 4 parallel agents.

## Tasks Created
- [ ] #24 - Evaluation harness (parallel: true)
- [ ] #25 - Stripe sandbox deposits (parallel: true)
- [ ] #26 - Conflict-aware slot suggestions (parallel: true)
- [ ] #27 - Bilingual retrieval (parallel: true)

Total tasks: 4
Parallel tasks: 4
Sequential tasks: 0
Estimated total effort: 14 hours
