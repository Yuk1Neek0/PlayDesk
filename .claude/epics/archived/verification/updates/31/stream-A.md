---
issue: 31
stream: Environment smoke check
started: 2026-05-22T12:40:19Z
status: completed
---

## Scope

Boot the full `docker compose` stack and confirm it is in a verifiable
state before Streams A–D (#32–#35) run.

## Outcome

All acceptance criteria pass — see `environment-record.md` for the full
table. Stack boots green on `docker compose up`; KB ingested (60 chunks,
30 en / 30 zh); seed data present; EXCLUDE constraint + HNSW index in place.

Two Docker-only integration bugs found and fixed in-stream:
1. Missing `frontend/public/` broke the frontend image build — fixed
   with `frontend/public/.gitkeep` (commit `8d2c67e`).
2. `ingest_kb` KB path unresolvable in-container — fixed by mounting
   `./knowledge-base` and adding `ingest_kb` to the backend boot command.

Downstream streams #32–#35 are unblocked. Stream D (#35) still needs
Stripe test-mode keys added to `epic-verification/.env`.
