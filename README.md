# PlayDesk

An AI-powered booking and front-desk platform for game lounges — PS5 / Switch / board games / private rooms. A customer can book a station through a manual flow or by chatting with an AI front desk that checks availability, answers policy questions from a knowledge base, and creates bookings.

**Stack:** Django + DRF · Next.js + Tailwind · Postgres + pgvector · hand-rolled agent loop · RAG

## Repository Layout

| Path | Contents |
|------|----------|
| `backend/` | Django 4.x + DRF — models, agent tools, tests |
| `frontend/` | Next.js (App Router) + Tailwind — `/`, `/chat`, `/admin` |
| `docs/contracts/` | Frozen interface contracts: OpenAPI, SSE protocol, KB format, eval format |
| `knowledge-base/` | RAG source content (English + 中文) |
| `docker-compose.yml` | `db` (pgvector), `backend`, `frontend` |
| `.claude/` | CCPM workflow — PRDs, epics, tasks |
| `cosready_demo_dev_plan.md` | Full product & development plan |

## Quickstart

Requires Docker Desktop.

```bash
cp .env.example .env      # then fill in any API keys
docker compose up         # boots db + backend + frontend
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000

## Development

**Backend** (from `backend/`):
```bash
pip install -r requirements.txt -r requirements-dev.txt
python manage.py migrate          # needs the Compose `db` service running
python manage.py seed_data        # load demo stores/resources
pytest
ruff check . && ruff format --check .
```

**Frontend** (from `frontend/`):
```bash
npm install
npm run lint && npm run typecheck && npm test && npm run build
```

## Project Management

PlayDesk is built with the **CCPM** workflow (`.claude/skills/ccpm`): every feature goes PRD → epic → GitHub issues → parallel agents. CI (`.github/workflows/ci.yml`) lints, type-checks, and tests both stacks against a pgvector Postgres service.
