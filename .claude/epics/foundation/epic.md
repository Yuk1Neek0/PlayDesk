---
name: foundation
status: backlog
created: 2026-05-21T19:06:21Z
progress: 0%
prd: .claude/prds/foundation.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/8
---

# Epic: foundation

## Overview

Scaffold the PlayDesk monorepo and freeze the seven contracts that let Wave 1 run as parallel agents. The epic is split into three conflict-free directory domains — `backend/`, `frontend/`, and `docs/`+`knowledge-base/` — so the bulk of the work executes as three concurrent streams.

## Architecture Decisions

- **Monorepo, directory-partitioned.** `backend/` and `frontend/` are independent apps; `docs/contracts/` holds language-neutral contract artifacts; `knowledge-base/` holds RAG source content. Partitioning by top-level directory is what makes concurrent agents conflict-free.
- **Database-enforced invariants.** Booking overlap is rejected by Postgres via `EXCLUDE USING gist` over `(resource_id, tstzrange(start_time, end_time))` — never by application code. Requires the `btree_gist` extension, created in a migration.
- **Dockerized data layer.** `pgvector/pgvector:pg16` as a Compose service keeps the Windows dev host and CI identical.
- **Contracts as committed files.** OpenAPI, SSE protocol, tool schemas, KB format, and eval format are real artifacts under version control, not tribal knowledge.
- **Stubs over implementations.** Tools and endpoints ship as typed stubs returning representative data; Wave 1 swaps bodies without touching signatures.
- **Forward-compatible schema.** `Booking.status` includes `pending_payment`, `KnowledgeChunk` carries `lang`, and the `check_availability` schema carries a `suggestions` key — so Stripe, bilingual, and slot-suggestion work need no later migration.

## Technical Approach

### Frontend Components
Next.js + Tailwind (defaults only). Route shells for `/` (manual booking), `/chat` (AI front desk), `/admin` (staff dashboard). Dummy one-click auth. vitest + a `typecheck` npm script so the CI `frontend` job goes green. Pages render static placeholders against the OpenAPI-generated types.

### Backend Services
Django 4.x + DRF project. The 7 models with migrations and the `EXCLUDE` constraint. Six agent-tool Pydantic schemas plus a tool registry, stubbed. ruff + pytest configured; a test proving concurrent-insert rejection. Seed fixtures for stores/resources/game menu.

### Infrastructure
Root `docker-compose.yml` (backend, frontend, pgvector), `.env.example`, and verification that the committed `.github/workflows/ci.yml` activates its `backend`/`frontend` jobs against the new scaffold.

## Implementation Strategy

Three concurrent execution streams, each owning a disjoint directory set:

- **Stream Backend** — tasks 001 → 002 → 005 (serial within the stream; all under `backend/` + root `docker-compose.yml`).
- **Stream Frontend** — task 003 (all under `frontend/`).
- **Stream Contracts** — tasks 004 + 006 (all under `docs/` + `knowledge-base/`).

Task 007 (CI activation + project docs) is integration work done once the three streams land. No two tasks across streams touch the same file.

## Task Breakdown Preview

- **001** Backend scaffold & dev environment — Django/DRF project, Docker Compose, pgvector, tooling.
- **002** Data layer — 7 models, migrations, `EXCLUDE` overlap constraint, seed fixtures, overlap test.
- **003** Frontend scaffold & page shells — Next.js, Tailwind, `/` `/chat` `/admin` shells, dummy auth, vitest.
- **004** API & streaming contracts — `openapi.yaml`, SSE protocol doc, TS type generation.
- **005** Agent tool contracts & registry — 6 Pydantic tool schemas + stubbed registry.
- **006** Knowledge base content & format — EN + 中 KB content + format spec + eval-case format.
- **007** CI activation & project docs — verify CI jobs go green, README, update CLAUDE.md.

## Dependencies

- Docker Desktop available on the dev/CI host.
- `.github/workflows/ci.yml` already committed (progressive-activation pipeline).
- No external blocking dependencies; all source material is in `cosready_demo_dev_plan.md`.

## Success Criteria (Technical)

- `docker compose up` boots all three services unattended.
- `migrate` applies the `EXCLUDE` constraint; the overlap test passes (one insert succeeds, one raises `IntegrityError`).
- CI `backend` + `frontend` jobs run and pass on the foundation branch.
- All seven contract artifacts are committed and mutually consistent.
- A Wave 1 epic can be decomposed with every task at `depends_on: []`.

## Estimated Effort

- Stream Backend: ~10h · Stream Frontend: ~5h · Stream Contracts: ~6h · Integration (007): ~2h.
- Wall-clock with 3 concurrent streams: ~10h (vs. ~23h serial).

## Tasks Created
- [ ] 001.md - Backend scaffold & dev environment (parallel: false)
- [ ] 002.md - Data layer: models, migrations & overlap constraint (parallel: false)
- [ ] 003.md - Frontend scaffold & page shells (parallel: true)
- [ ] 004.md - API & streaming contracts (parallel: true)
- [ ] 005.md - Agent tool contracts & registry (parallel: false)
- [ ] 006.md - Knowledge base content & format (parallel: true)
- [ ] 007.md - CI activation & project docs (parallel: false)

Total tasks: 7
Parallel tasks: 3
Sequential tasks: 4
Estimated total effort: ~23 hours (~10h wall-clock with 3 streams)
