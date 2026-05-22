---
name: verification
status: backlog
created: 2026-05-22T12:27:10Z
updated: 2026-05-22T12:35:59Z
progress: 0%
prd: .claude/prds/verification.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/30
---

# Epic: verification

## Overview

Boot the full PlayDesk stack via `docker compose` and verify every acceptance criterion in `cosready_demo_dev_plan.md` against a live, integrated system — fixing the integration bugs that the per-epic mock-based suites structurally cannot catch. Work is partitioned into four verification streams by code domain, run as parallel agents, then reconciled by a final integration pass.

## Architecture Decisions

- **Verify, don't rebuild.** No new product code. Agents exercise existing endpoints/flows and fix only what is broken. The dev plan's acceptance criteria are the authoritative checklist.
- **Partition by code domain, not by layer.** Stream A owns `api/`, B owns `agent/`+`rag/`+`agent_tools/`, C owns `frontend/`, D owns `evals/`+`payments.py`. This keeps the *fix* surface — not just the test surface — mostly disjoint.
- **Shared files are integration-owned.** In-stream fixes that must touch `config/settings.py`, `config/urls.py`, or `frontend/src/types/api.d.ts` are flagged `conflicts_with`; the final integration task reconciles them on the epic branch.
- **Live externals.** Agent verification makes real LLM calls; Stripe uses real test-mode keys with `stripe listen`. Secrets come from env/`.env`, never committed.
- **Evidence over assertion.** Each stream emits a verification record (criterion → pass/fail → command/evidence) so the demo checklist is reproducible.

## Technical Approach

### Frontend Components
- `/`, `/chat`, `/admin` exercised against the live backend instead of mocked fetch/SSE.
- Likely fix surface: API base URL / SSE event-name drift between `frontend/src/lib/{api,sse}.ts` and the backend; `types/api.d.ts` regeneration if the OpenAPI contract drifted.

### Backend Services
- `api/` — booking CRUD `curl` round-trip; concurrent-insert `409` (two simultaneous POSTs); admin endpoints.
- `agent/` + `rag/` + `agent_tools/` — NL booking, RAG-vs-SQL routing, `Message` trace integrity, 6-iteration fallback, SSE incremental emission.
- `evals/` — harness replays curated set against the live agent, reports accuracy.
- `core/payments.py` — Stripe Checkout → webhook → status transition; `expire_holds` TTL command.

### Infrastructure
- `docker compose up` (`db` + `backend` + `frontend`) on the Windows host is the verification environment.
- `stripe listen` forwards webhooks to the local backend for Stream D.
- No CI or cloud changes.

## Implementation Strategy

1. **Task 001 — Environment smoke check** (blocking): confirm `docker compose up` boots all three services, migrations apply, KB is ingested, seed data present. Unblocks everything else.
2. **Tasks 002–005 — four verification streams**, fully parallel after 001:
   - 002 Stream A — Backend REST & SSE
   - 003 Stream B — Agent loop & RAG
   - 004 Stream C — Frontend integration
   - 005 Stream D — Enhancements (evals, Stripe, suggestions, bilingual)
3. **Task 006 — Integration & sign-off** (blocking on 002–005): reconcile any shared-file fixes, re-run full `pytest` + `npm` suites, confirm the green end-to-end demo path, assemble the consolidated verification record.

Each stream agent verifies its criteria, fixes failures in-stream, and writes its verification record.

## Task Breakdown Preview

- [ ] **001** Environment smoke check — stack boots, migrations, KB ingest, seed data
- [ ] **002** Stream A: backend REST CRUD round-trip, concurrent-insert 409, SSE incremental emission
- [ ] **003** Stream B: NL booking, RAG-vs-SQL routing, Message trace, iteration-cap fallback
- [ ] **004** Stream C: frontend `/`, `/chat`, `/admin` against live backend, no-refresh propagation
- [ ] **005** Stream D: eval harness accuracy, Stripe test-mode deposit flow, slot suggestions, bilingual
- [ ] **006** Integration & sign-off — reconcile shared fixes, full suites green, consolidated record

## Dependencies

- All four build epics merged to `main` — satisfied (`e1d59e7`).
- `docker compose` boots on the dev host (verified by Task 001).
- Stripe test-mode keys + `stripe` CLI, and a live LLM API key, available to the developer.
- 002–005 depend on 001; 006 depends on 002–005.

## Success Criteria (Technical)

- 100% of dev plan acceptance criteria (§1.1–1.5, §2.1–2.4) pass against the live stack, with evidence.
- Backend `pytest` and frontend `npm run lint && typecheck && test && build` pass after all fixes.
- Booking via `/chat` appears in `/admin` with no refresh — demonstrated live.
- Two concurrent inserts → exactly one `200` + one `409`.
- Epic merges to `main` with a per-stream verification record and a consolidated demo checklist.

## Estimated Effort

- 6 tasks. 001 and 006 are sequential bookends; 002–005 are four parallel agents.
- Critical path: 001 → (longest of 002–005, likely 003 or 005) → 006.
- Fix volume is unknown until the streams run — estimate scales with how far the contracts drifted.

## Tasks Created
- [ ] #31 - Environment smoke check (parallel: false)
- [ ] #32 - Stream A: backend REST & SSE verification (parallel: true)
- [ ] #33 - Stream B: agent loop & RAG verification (parallel: true)
- [ ] #34 - Stream C: frontend integration verification (parallel: true)
- [ ] #35 - Stream D: enhancements verification (parallel: true)
- [ ] #36 - Integration & sign-off (parallel: false)

Total tasks: 6
Parallel tasks: 4 (002–005, after 001)
Sequential tasks: 2 (001, 006)
Estimated total effort: 25 hours
