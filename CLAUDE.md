# CLAUDE.md

> Think carefully and implement the most concise solution that changes as little code as possible.

## Project

**PlayDesk** — an AI-powered booking and front-desk platform for game lounges (PS5 / Switch / board games / private rooms). Stack: Django + DRF, Next.js, Postgres + pgvector, a hand-rolled agent loop, and RAG.

Product and delivery plan live in `.claude/prds/` (foundation, backend-core, frontend, enhancements, verification) and their archived epics under `.claude/epics/archived/`.

## Repository Layout

- `backend/` — Django 4.x + DRF app, models, agent tools, tests.
- `frontend/` — Next.js (App Router) + Tailwind.
- `docs/contracts/` — frozen interface contracts (OpenAPI, SSE protocol, KB format, eval format).
- `knowledge-base/` — RAG source content (EN + 中).
- `docker-compose.yml` — `db` (pgvector), `backend`, `frontend`.
- `.claude/` — CCPM workflow: PRDs, epics, tasks.

## Workflow

This project uses **CCPM** (`.claude/skills/ccpm`). Work is planned as PRD → epic → GitHub issues → parallel agents. Speak in CCPM terms: "create a PRD for X", "decompose the X epic", "sync the X epic", "what's our status".

## Quickstart

```bash
docker compose up        # boots db + backend + frontend
```

After `docker compose up`, you can switch between PlayDesk Flagship and PlayDesk North in the admin nav (v6 multi-location).

## Testing

Always run tests before committing:
- Backend (from `backend/`): `pytest` — requires the Compose `db` service running.
- Frontend (from `frontend/`): `npm run lint && npm run typecheck && npm test && npm run build`.

## Code Style

- Backend: `ruff check` + `ruff format` must pass.
- Frontend: ESLint (`npm run lint`) + strict TypeScript must pass.
- Follow existing patterns in the codebase.

## Key Invariants

- Booking overlap is rejected by Postgres (`EXCLUDE USING gist` + `btree_gist`), never by application code.
- RAG handles unstructured Q&A; SQL/tools handle structured queries (availability, pricing, booking state).
