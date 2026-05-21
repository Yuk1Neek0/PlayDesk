---
name: backend-core
status: backlog
created: 2026-05-21T19:51:40Z
progress: 0%
prd: .claude/prds/backend-core.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/16
---

# Epic: backend-core

## Overview

Replace the foundation stubs with the working backend: REST API, real agent tools, RAG retrieval, the hand-rolled agent loop, and SSE streaming. Decomposed so the bulk runs as three concurrent agents owning disjoint Django apps.

## Architecture Decisions

- **One Django app per concern.** `api/` (REST), `rag/` (retrieval + ingest), `agent/` (loop + streaming); tool bodies live in the existing `agent_tools/`. Disjoint apps keep concurrent agents conflict-free.
- **No shared-file edits by build agents.** Agents do not touch `config/settings.py` or `config/urls.py`; they report the `INSTALLED_APPS`, settings, and URL includes they need, and integration wires them.
- **Stubs swapped, signatures untouched.** Real tool bodies replace stubs behind the frozen Pydantic schemas — the registry and the agent loop are unaffected.
- **Provider calls are injectable.** LLM and embedding clients sit behind thin interfaces so tests mock them and CI runs without API keys.
- **DB-enforced invariants stand.** Booking overlap remains a Postgres `409` via the existing `EXCLUDE` constraint; the API surfaces it, never re-implements it.

## Technical Approach

### Backend Services
- **`api/`** — DRF serializers/views/urls for resources (+type filter), availability computation (business hours − bookings), booking CRUD (`409` on overlap), admin conversations/bookings.
- **`rag/`** — KB ingest management command, `text-embedding-3-small` embeddings, pgvector HNSW index, top-5 retrieval; `search_knowledge_base` real body.
- **`agent_tools/`** — real bodies for the 6 tools, wired to the DB.
- **`agent/`** — hand-rolled loop (context assembly, LLM call, parallel tool dispatch, 6-iter cap + fallback, per-turn persistence), system prompt with RAG-vs-SQL partition, and the SSE streaming message endpoint.

### Infrastructure
No new infra — uses the foundation's Compose DB and CI. New settings (LLM/embedding config) extend `.env.example`.

## Implementation Strategy

Three concurrent agents on disjoint apps:
- **Stream API** — task 001 (`api/`).
- **Stream RAG+Tools** — tasks 002, 003 (`rag/`, `agent_tools/`).
- **Stream Agent** — tasks 004, 005, 006 (`agent/`).

Integration wires `config/urls.py` + `config/settings.py` and runs the full suite.

## Task Breakdown Preview

- **001** REST API — resources, availability, booking CRUD, admin endpoints.
- **002** RAG layer — ingest command, embeddings, pgvector HNSW retrieval.
- **003** Agent tools — real implementations of the 6 tools.
- **004** Hand-rolled agent loop — context assembly, tool dispatch, retries, persistence.
- **005** SSE streaming endpoint — streaming conversation messages.
- **006** System prompt & integration tests — RAG-vs-SQL partition, end-to-end agent tests.

## Dependencies

- The merged `foundation` epic (models, contracts, tool schemas, KB content).

## Success Criteria (Technical)

- `curl` round-trip creates/queries/cancels a booking; concurrent same-slot inserts → one `409`.
- The agent completes a booking from one natural-language message; `Message` rows show the full trace.
- Streaming endpoint emits tokens incrementally.
- RAG-vs-SQL routing correct on smoke tests.
- CI green with LLM/embeddings mocked.

## Estimated Effort

- Stream API ~6h · Stream RAG+Tools ~8h · Stream Agent ~9h · Integration ~3h.
- Wall-clock with 3 concurrent streams: ~9h.

## Tasks Created
- [ ] 001.md - REST API: resources, availability, booking CRUD, admin (parallel: true)
- [ ] 002.md - RAG layer: ingest, embeddings, pgvector retrieval (parallel: true)
- [ ] 003.md - Agent tools: real implementations of the 6 tools (parallel: false)
- [ ] 004.md - Hand-rolled agent loop (parallel: false)
- [ ] 005.md - SSE streaming endpoint (parallel: false)
- [ ] 006.md - System prompt & integration tests (parallel: false)

Total tasks: 6
Parallel tasks: 2
Sequential tasks: 4
Estimated total effort: ~26 hours (~9h wall-clock with 3 streams)
