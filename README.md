# PlayDesk

<!-- DEMO GIF -->
<p align="center">
  <img src="docs/assets/demo.gif" alt="PlayDesk demo" width="800" />
</p>
<!-- /DEMO GIF -->

An AI-powered booking and front-desk platform for game lounges — PS5 / Switch / board games / private rooms. Customers book a station through a branded manual flow or by chatting with an AI front desk that checks availability, answers policy questions from a knowledge base, quotes pricing, and creates bookings end-to-end.

**Stack:** Django 4 + DRF · Next.js (App Router) + Tailwind · Postgres + pgvector · Stripe · Twilio (SMS / WhatsApp / Voice) · hand-rolled agent loop · RAG

## Features

- **AI front desk** — streaming agent loop with tool use (availability, quoting, booking, knowledge base) over SSE
- **Booking** — branded `/s/[slug]/book` flow, deposit + balance via Stripe, Postgres-enforced overlap (`EXCLUDE USING gist`)
- **Pricing engine** — pluggable rule strategies, store-scoped quotes shared by agent + manual flows
- **Customer portal** — `/s/[slug]/account` with OTP login, bookings, memberships, rewards
- **Memberships & rewards** — tier system, point ledger, redemption flows
- **Campaigns & outbound** — segments DSL, scheduled SMS/WhatsApp runs, quiet-hours + opt-out
- **Check-in** — rotating QR (`/c-in?k=`), per-booking token links (`/c/[token]`), manual admin check-in
- **Multi-location** — store switcher across admin, request-scoped data, cross-store isolation
- **Retention** — churn scoring, cohort filters, re-engagement campaigns
- **Admin** — business-dashboard tiles, payments ledger, staff auth (`StaffOnlyMiddleware`), branded QR landing

## Repository Layout

| Path | Contents |
|------|----------|
| `backend/` | Django 4.x + DRF — `core`, `billing`, `campaigns`, `outbound`, `pricing`, `checkin`, `agent`, `rag` |
| `frontend/` | Next.js (App Router) + Tailwind — `/`, `/chat`, `/qr/[slug]`, `/s/[slug]/{book,account}`, `/c-in`, `/c/[token]`, `/admin/*`, `/staff/login` |
| `docs/contracts/` | Frozen interface contracts: OpenAPI, SSE protocol, KB format, eval format |
| `knowledge-base/` | RAG source content (English + 中文) |
| `docker-compose.yml` | `db` (pgvector), `backend`, `frontend` (+ dev override for hot-reload) |
| `.claude/` | CCPM workflow — PRDs, epics, tasks (archived per release) |
| `cosready_demo_dev_plan.md` | Full product & development plan |

## Quickstart

Requires Docker Desktop.

```bash
cp .env.example .env      # then fill in any API keys
docker compose up         # boots db + backend + frontend
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000

After boot, switch between **PlayDesk Flagship** and **PlayDesk North** in the admin nav (v6 multi-location).

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

End-to-end suites live under `frontend/e2e/` (Playwright) — booking, customer portal, rotating check-in, multi-location, retention, staff auth.

## Key Invariants

- Booking overlap is rejected by Postgres (`EXCLUDE USING gist` + `btree_gist`), never by application code.
- RAG handles unstructured Q&A; SQL/tools handle structured queries (availability, pricing, booking state).
- All admin endpoints sit behind `StaffOnlyMiddleware`; customer surfaces use OTP-based session middleware.

## Project Management

PlayDesk is built with the **CCPM** workflow (`.claude/skills/ccpm`): every feature goes PRD → epic → GitHub issues → parallel agents → archived under `.claude/epics/archived/`. CI (`.github/workflows/ci.yml`) lints, type-checks, and tests both stacks against a pgvector Postgres service, plus a separate integrity workflow for LLM-touching evals.
