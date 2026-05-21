---
name: backend-core
description: The working PlayDesk backend — REST API, real agent tools, RAG layer, hand-rolled agent loop, and SSE streaming, all against the frozen foundation contracts.
status: backlog
created: 2026-05-21T19:51:40Z
---

# PRD: backend-core

## Executive Summary

backend-core is the critical-path epic of Wave 1: it replaces the foundation's stubs with the real backend. It implements the REST API, the six agent tools, the RAG retrieval layer, the hand-rolled agent loop, and the SSE streaming endpoint — every piece building against contracts already frozen in foundation (OpenAPI, SSE protocol, tool schemas, data schema).

## Problem Statement

Foundation froze the interfaces but shipped only stubs. Nothing yet computes availability, creates a booking, retrieves knowledge, or runs a conversation. backend-core makes the product actually work end to end on the server side, so the frontend and the enhancements epic have a real system to build on.

## User Stories

- **As a customer**, I can create, view, and cancel a booking via the REST API, and a double-book is rejected with `409`.
  - *Acceptance:* `curl` round-trip creates/queries/cancels; concurrent same-slot inserts → one success, one `409`.
- **As a customer**, I can ask the AI front desk a natural-language question and get a correct answer — policy questions from the knowledge base, availability from the database.
  - *Acceptance:* "Can I bring outside food?" → answered from RAG; "Is room 3 free at 8pm?" → answered via `check_availability`, never RAG.
- **As a customer**, the AI completes a booking from a single message like "Saturday 8pm, PS5 for 3, ~2 hours".
- **As a developer**, every conversation turn (user / assistant / tool call / tool result) is persisted as a `Message` row, giving a readable end-to-end reasoning trace.
- **As a client**, the streaming endpoint emits assistant tokens incrementally over SSE.

## Functional Requirements

1. **REST API** — resources list (filter by type), availability computation, booking CRUD (`409` on overlap), admin conversations/bookings — per `docs/contracts/openapi.yaml`.
2. **Agent tools** — real implementations of all 6 tools (replace foundation stubs), wired to the database.
3. **RAG layer** — KB ingest management command, OpenAI `text-embedding-3-small` embeddings, pgvector retrieval with an HNSW index, top-5 search.
4. **Agent loop** — hand-rolled: context assembly (system prompt + RAG chunks + history), LLM call, parallel tool dispatch, 6-iteration cap with human-handoff fallback, full per-turn persistence.
5. **SSE streaming** — `POST /api/conversations/{id}/messages` streams assistant tokens + tool-call hints per the SSE protocol.
6. **RAG-vs-SQL partition** — the system prompt directs unstructured Q&A to RAG and structured queries to SQL tools.

## Non-Functional Requirements

- LLM (Claude) and embedding API calls are mocked in tests — CI runs without API keys.
- LLM API failure → exponential backoff, max 3 retries; tool failure → structured error returned to the LLM, never raised to the user.
- Tool/LLM payloads persisted as JSONB for inspection.

## Success Criteria

- The agent completes a booking from one natural-language message.
- The `Message` table shows a full, readable reasoning trace after a conversation.
- The streaming endpoint emits tokens incrementally, not as one payload.
- RAG-vs-SQL routing is correct on smoke-test conversations.
- CI green: lint, migrations, full pytest suite (LLM/embeddings mocked).

## Constraints & Assumptions

- Builds strictly against the frozen foundation contracts; contract changes are out of scope.
- Postgres + pgvector with HNSW; fall back to IVFFlat only if HNSW is unavailable.
- Django + DRF; SSE via Django `StreamingHttpResponse`.

## Out of Scope

- Frontend wiring (the `frontend` epic).
- Stripe, evaluation harness, conflict-aware slot suggestions, bilingual retrieval filtering (the `enhancements` epic).

## Dependencies

- The merged `foundation` epic — models, contracts, tool schemas, KB content.
