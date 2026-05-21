---
name: enhancements
description: The nice-to-have layer — evaluation harness, Stripe deposits, conflict-aware slot suggestions, and bilingual retrieval.
status: backlog
created: 2026-05-21T19:51:40Z
---

# PRD: enhancements

## Executive Summary

The `enhancements` epic adds the four nice-to-have capabilities from the dev plan, each independent of the others: an evaluation harness, Stripe sandbox deposits, conflict-aware slot suggestions, and bilingual retrieval. The foundation contracts already reserved hooks for all four (eval-case format, `pending_payment` status, `suggestions` key, `lang` field), so none requires a schema change.

## Problem Statement

backend-core makes PlayDesk work; enhancements make it demo-compelling and production-credible. Evals signal that AI is treated as a production system; Stripe matches the COSReady stack; slot suggestions convert refusals into bookings; bilingual handling addresses an international user base.

## User Stories

- **As an engineer**, I can replay a labeled test set against the agent and get per-case pass/fail plus aggregate accuracy.
- **As a customer**, I can pay a deposit via Stripe Checkout (test mode); on success my booking flips from `pending_payment` to `confirmed`.
- **As a customer**, when my requested time is unavailable I'm offered 1–2 nearby alternatives instead of a flat refusal.
- **As a Chinese-speaking customer**, the assistant answers in 中文 and retrieves Chinese knowledge-base chunks.

## Functional Requirements

1. **Evaluation harness** — 10–15 labeled conversations (`should_book` / `should_clarify` / `should_refuse` / `should_search_kb`); a replay script asserting correct tool use, booking outcome, and on-topic final message; outputs per-case + aggregate accuracy.
2. **Stripe sandbox** — deposit via Checkout (test mode); webhook flips `pending_payment` → `confirmed`; a periodic command expires stale `pending_payment` bookings.
3. **Slot suggestions** — when `check_availability` finds nothing, the tool returns 1–2 nearby alternatives in its `suggestions` field; the LLM relays them.
4. **Bilingual retrieval** — detect user-message language, filter KB retrieval by `lang`, instruct the LLM to answer in the user's language.

## Non-Functional Requirements

- Stripe and LLM calls mocked in tests; CI runs without secrets.
- Each capability is independently shippable.

## Success Criteria

- The eval script reports aggregate accuracy across all labeled cases.
- A Stripe test-mode payment confirms a booking via webhook.
- An unavailable request yields relayed alternatives.
- A Chinese query is answered in Chinese from `lang: zh` chunks.

## Constraints & Assumptions

- All four contract hooks already exist from foundation — no migrations expected.
- Stripe in test mode only.

## Out of Scope

- Production payment hardening, fraud handling, additional languages beyond EN/中.

## Dependencies

- The `backend-core` epic — agent loop, tools, RAG, and booking flow must exist first.
