---
name: foundation
description: Monorepo scaffold, Dockerized pgvector dev environment, CI activation, and the seven frozen contracts that let Wave 1 fan out in parallel.
status: backlog
created: 2026-05-21T19:06:21Z
---

# PRD: foundation

## Executive Summary

Foundation is Wave 0 of PlayDesk — the only deliberately serial wave. It scaffolds the Django + Next.js monorepo, stands up a Dockerized Postgres + pgvector development environment, activates the CI pipeline, and **freezes seven contracts** (data schema, REST/OpenAPI, agent tool interfaces, SSE event protocol, knowledge-base format, tool registry, eval-case format).

Freezing every interface up front collapses the natural dependency chains (tools need models, the agent loop needs tools, the frontend needs the API). Downstream work then waits only on a *contract*, never on an *implementation* — so the Wave 1 build epics decompose into ~19 issues that run as parallel agents in conflict-free worktrees.

## Problem Statement

PlayDesk must ship a working vertical slice quickly for the COSReady demo. A naive layered build ("all backend, then all frontend") serializes the work and makes the riskiest pieces — the Postgres `EXCLUDE` overlap constraint and the streaming agent loop — surface late. The foundation removes artificial serialization by making every seam an explicit, committed artifact before feature work begins, and front-loads the highest-risk piece (the `EXCLUDE` constraint) so it fails early when it is cheap to fix.

## User Stories

- **As a developer**, I can run `docker compose up` and get the backend, frontend, and a Postgres+pgvector database running, so onboarding is one command.
  - *Acceptance:* both apps boot; the DB has `vector` and `btree_gist` extensions enabled.
- **As a Wave 1 agent**, I can build a feature against a frozen contract (OpenAPI spec, tool schema, SSE protocol) without waiting on the upstream implementation, so build issues run concurrently.
  - *Acceptance:* every Wave 1 task can declare `depends_on: []`; a non-empty `depends_on` signals a missed contract.
- **As a reviewer**, I see CI run lint, typecheck, and tests for any code that lands, so quality gates exist from commit one.
  - *Acceptance:* the `backend` and `frontend` CI jobs activate automatically once their scaffold lands and pass green.
- **As the team**, the booking overlap guarantee is enforced by the database, so concurrent bookings cannot double-book a resource.
  - *Acceptance:* a test proves two concurrent inserts at the same `(resource_id, time)` yield one success and one rejection.

## Functional Requirements

1. **Monorepo layout** — `backend/` (Django), `frontend/` (Next.js), `docs/contracts/`, `knowledge-base/`, root `docker-compose.yml`.
2. **Dev environment** — `docker-compose.yml` with a `pgvector/pgvector:pg16` service; `.env.example`; one-command boot.
3. **Backend skeleton** — Django 4.x + DRF project, `requirements.txt` / `requirements-dev.txt`, ruff + pytest configured, `manage.py` present.
4. **Data layer** — the 7 models (`Store`, `Resource`, `GameMenu`, `Booking`, `Conversation`, `Message`, `KnowledgeChunk`) with migrations, the `EXCLUDE USING gist` booking-overlap constraint (via `btree_gist`), and seed fixtures.
5. **Frontend skeleton** — Next.js + Tailwind (defaults only), route shells for `/`, `/chat`, `/admin`, dummy auth, vitest + `typecheck` script.
6. **Contract: REST/OpenAPI** — `docs/contracts/openapi.yaml` covering every planned endpoint; TS type generation wired.
7. **Contract: SSE protocol** — `docs/contracts/sse-protocol.md` defining event names and payloads (`token`, `tool_call_start`, `tool_call_end`, `done`, `error`).
8. **Contract: agent tools** — 6 Pydantic tool schemas + a tool registry, stubbed to return representative data.
9. **Contract: knowledge base** — KB content (game catalog, room/table specs, hours, policies, FAQ) authored in EN + 中, plus a format spec; `KnowledgeChunk` carries `category`, `source`, `lang`.
10. **Contract: eval cases** — `docs/contracts/eval-format.md` defining the labeled test-conversation JSON schema.
11. **CI activation** — the existing `.github/workflows/ci.yml` `backend`/`frontend` jobs activate and pass against the new scaffold.

## Non-Functional Requirements

- Postgres 16 with `pgvector` and `btree_gist` extensions.
- Python 3.12; Node 20.
- Lint/format: ruff (backend), ESLint (frontend). Tests: pytest (backend), vitest (frontend).
- Nice-to-have hooks designed into contracts now to avoid later migrations: `check_availability` response carries a `suggestions` key; `KnowledgeChunk.lang`; `Booking.status` includes `pending_payment`.

## Success Criteria

- `docker compose up` boots backend + frontend + pgvector with no manual steps.
- `python manage.py migrate` applies cleanly, including the `EXCLUDE` constraint.
- An automated test proves the concurrent-insert overlap rejection (one success, one `IntegrityError`).
- CI `backend` and `frontend` jobs both run and pass on the foundation branch.
- All seven contract artifacts exist, are committed, and are internally consistent.
- A Wave 1 epic can be decomposed where every task has `depends_on: []`.

## Constraints & Assumptions

- Development host is Windows; the toolchain must work cross-platform (Docker-based DB).
- Stack is fixed by the dev plan: Django 4.x + DRF, Next.js + Tailwind, Postgres + pgvector, hand-rolled agent loop, RAG.
- LLM target is Claude; embeddings via OpenAI `text-embedding-3-small`.
- Contracts are authored from the existing `cosready_demo_dev_plan.md`; no further requirements gathering is needed.

## Out of Scope

Everything below is Wave 1+ and explicitly excluded from foundation:

- Agent loop logic, real tool implementations, RAG retrieval/embedding.
- Real business logic behind REST endpoints (availability computation, booking CRUD behavior).
- Real frontend ↔ backend wiring (pages ship as shells against mocks).
- Stripe, evaluation harness execution, conflict-aware slot suggestion logic, bilingual retrieval filtering.

## Dependencies

- Docker Desktop on the dev host.
- GitHub CLI (`gh`) authenticated; CCPM workflow installed.
- The CI workflow `.github/workflows/ci.yml` (already committed).
