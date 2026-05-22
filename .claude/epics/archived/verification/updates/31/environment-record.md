# Environment Record — Issue #31 (Environment smoke check)

Verified: 2026-05-22
Stack: `docker compose up -d --build` from the `epic-verification` worktree.

## Service health

| Service | Image | Status | Port |
|---|---|---|---|
| db | `pgvector/pgvector:pg16` | Up, healthy | 5432 |
| backend | Django 4.2.16 (built) | Up | 8000 |
| frontend | Next.js 14.2.35 (built) | Up | 3000 |

## Acceptance criteria

| Criterion | Result | Evidence |
|---|---|---|
| `docker compose up` brings all 3 services healthy | ✅ | `docker compose ps` — all Up |
| Migrations apply cleanly | ✅ | `core.0001_extensions`, `core.0002_initial_models`, `core.0003_knowledgechunk_hnsw_index` all OK |
| `btree_gist` + `vector` extensions, EXCLUDE constraint | ✅ | `pg_extension` has both; `pg_constraint` contype='x' → `booking_no_overlap` |
| KB ingested, chunks exist in both langs | ✅ | `core_knowledgechunk`: 60 rows — 30 `en`, 30 `zh` |
| pgvector HNSW index present | ✅ | index `knowledge_chunk_embedding_hnsw` on `core_knowledgechunk` |
| Seed data present | ✅ | 1 Store, 5 Resources (2 PS5, 1 Switch, 1 Private Room, 1 Board Game Table), 8 Games |
| backend reachable, frontend serves pages | ✅ | `GET /api/resources/` → 200; `GET /` → 200 |
| Required env/secrets present | ✅ | Real `OPENAI_API_KEY` (embeddings verified working) + `ANTHROPIC_API_KEY` in worktree `.env` |

## Bugs found and fixed in-stream

1. **frontend Docker build failed** — `frontend/Dockerfile` copies `/app/public`
   into the runner stage, but no `frontend/public/` directory existed (Next.js
   does not require one). CI ran `npm run build` directly and never exercised
   the Docker build. **Fix:** added `frontend/public/.gitkeep`.
   Commit `8d2c67e`.

2. **`ingest_kb` could not find the knowledge base** — its default KB path
   resolves to `parents[4]/knowledge-base`. On the host that is
   `<repo>/knowledge-base`, but inside the container `backend/` is mounted at
   `/app`, so `parents[4]` is `/` → it looked for `/knowledge-base`, which was
   not mounted. **Fix:** in `docker-compose.yml`, mounted
   `./knowledge-base:/knowledge-base:ro` and added `python manage.py ingest_kb`
   to the backend boot command so a plain `docker compose up` is self-sufficient.

## Notes for downstream streams

- The `.env` lives in the worktree root: `epic-verification/.env`. The stack
  reads it from there, NOT from the main repo.
- `OPENAI_API_KEY` (embeddings/RAG) and `ANTHROPIC_API_KEY` (agent LLM) are both
  real and working. Stripe test-mode keys still needed before Stream D (#35).
- `docker-compose.yml` still carries an obsolete `version:` attribute — harmless
  warning, left untouched (out of scope).
