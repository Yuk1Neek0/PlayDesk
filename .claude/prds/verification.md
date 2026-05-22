---
name: verification
description: Wave 2 end-to-end verification of the full PlayDesk stack against a live backend, fixing integration bugs in-stream.
status: backlog
created: 2026-05-22T12:27:10Z
---

# PRD: verification

## Executive Summary

The four build epics — `foundation`, `backend-core`, `frontend`, `enhancements` — are all shipped and archived. Every must-have and nice-to-have in `cosready_demo_dev_plan.md` has been coded. But each epic was tested in isolation: the backend against its own `pytest` suite, the frontend against **mocked** fetch and SSE. The `frontend` epic explicitly deferred integrated testing — "Build against mocks… end-to-end verification is Wave 2."

This PRD defines Wave 2: boot the full stack via `docker compose` and verify the dev plan's acceptance criteria against a *live, integrated* system, fixing the integration bugs that mock-based tests structurally cannot catch.

## Problem Statement

Mocked tests prove each component honours a contract; they cannot prove the two sides agree on it. A frontend built against a hand-mocked SSE shape, a backend emitting a slightly different event name, and an OpenAPI client generated from a contract that drifted — each passes its own suite and the integrated flow still breaks. The dev plan's acceptance criteria are cross-component by nature (booking via `/chat` appearing in `/admin`; concurrent inserts producing exactly one `409`) and have never been exercised end-to-end. Until they are, "done" is unproven and the demo is not safe to present.

## User Stories

**As the developer demoing PlayDesk to COSReady**, I need every acceptance criterion in the dev plan to pass against the real running stack, so a live demo cannot surprise me.
- *Acceptance:* every criterion in §1.1, §1.2, §1.3, §1.4, §1.5, §2.1–2.4 is executed against `docker compose up` and recorded as pass, or fixed until it passes.

**As a customer**, I can complete a booking end-to-end through the AI chat and see it appear in the staff dashboard without a refresh.
- *Acceptance:* one natural-language message books a resource; the booking surfaces in `/admin` live; the chat UI never freezes during tool-call sequences.

**As staff**, the system rejects double-bookings at the database, not the application.
- *Acceptance:* two concurrent inserts at the same `(resource_id, time)` yield exactly one `200` and one `409`.

**As a reviewer of the AI design**, I can read a full conversation's reasoning trace from the `Message` table and see RAG-vs-SQL routing behaving correctly.
- *Acceptance:* policy questions resolve via `search_knowledge_base`; availability questions via `check_availability`; the trace is readable end-to-end.

## Functional Requirements

Verification is partitioned into four streams, each owning a disjoint set of acceptance criteria and (primarily) a disjoint code domain.

### Stream A — Backend REST & streaming (`backend/api/`, `backend/agent/` SSE)
- `curl` round-trip: create, query, modify, cancel a booking.
- Two concurrent inserts at the same `(resource_id, time)` → exactly one `200`, one `409`.
- SSE endpoint emits assistant tokens incrementally, not as a single payload.

### Stream B — Agent loop & RAG (`backend/agent/`, `backend/rag/`, `backend/agent_tools/`)
- A single message — *"Saturday 8pm, PS5 for 3 people, around 2 hours"* — completes a booking.
- RAG-vs-SQL routing: *"Can I bring outside food?"* → `search_knowledge_base`; *"Is room 3 free at 8pm tomorrow?"* → `check_availability`.
- The `Message` table holds the full turn-by-turn trace (user / assistant / tool call / tool result) and reads coherently.
- The 6-iteration cap produces the graceful human-handoff fallback.

### Stream C — Frontend integration (`frontend/`)
- `/` manual booking flow completes against the live REST API.
- `/chat` streams real tokens from the live SSE endpoint; tool-call hints render.
- A booking made via `/chat` appears in `/admin` without a manual refresh.
- The chat UI does not freeze during long tool-call sequences.

### Stream D — Enhancements (`backend/evals/`, `backend/core/payments.py`, slot suggestions, bilingual)
- The eval harness replays its curated set against the live agent and reports per-case pass/fail + aggregate accuracy.
- Stripe deposit flow verified with **real test-mode keys**: `create_booking` → Checkout → webhook → `Booking.status` moves `pending_payment` → `confirmed`; a `pending_payment` booking expires after its TTL.
- `check_availability` returns nearby `suggestions` when the requested slot is taken.
- A Chinese-language message retrieves `lang=zh` chunks and gets a Chinese reply.

### Cross-cutting
- Each stream produces a written verification record (pass/fail per criterion, with evidence).
- Bugs found are **fixed in-stream** on the epic branch. Trivial wiring fixes and structural fixes alike are made directly; nothing is deferred.
- A final integration pass confirms all four streams' fixes coexist and the full `docker compose` stack is green.

## Non-Functional Requirements

- **Environment:** local `docker compose up` (`db` + `backend` + `frontend`) on the Windows dev host. No cloud deploy in scope.
- **Reproducibility:** every verified criterion has a recorded command or steps so it can be re-run.
- **No regressions:** existing `pytest` and `npm` suites must still pass after fixes.
- **Secrets:** Stripe test-mode keys supplied via env / `.env`, never committed. LLM API key likewise.

## Success Criteria

- 100% of the dev plan's acceptance criteria (§1.1–1.5, §2.1–2.4) pass against the live stack.
- Backend `pytest` and frontend `npm run lint && typecheck && test && build` pass after all fixes.
- A customer can book via `/chat` and see it in `/admin` with no refresh — demonstrated, not asserted against a mock.
- The epic merges to `main` with a verification record per stream.

## Constraints & Assumptions

- Streams parallelize cleanly by code domain, but **in-stream fixes may touch shared files** (`config/settings.py`, `config/urls.py`, generated types). Such files are flagged as conflicts in decomposition and reconciled in the final integration pass.
- Real Stripe test-mode keys and a way to forward webhooks (`stripe listen`) are available to the developer.
- A live LLM API key is available; agent verification makes real model calls.
- The dev plan's acceptance criteria are the complete and authoritative checklist; no new product scope is added.

## Out of Scope

- Cloud/production deployment, hosting, CI changes.
- New product features beyond the dev plan.
- Authentication hardening, multi-store, performance/load testing.
- UI/visual redesign (`docs/claude-design-prompts.md` is a separate track).
- Rewriting mock-based unit tests — they stay; this adds integrated verification on top.

## Dependencies

- All four build epics merged to `main` — satisfied (`e1d59e7`).
- `docker compose` stack boots cleanly on the dev host.
- Stripe test-mode keys + `stripe` CLI; LLM API key.
