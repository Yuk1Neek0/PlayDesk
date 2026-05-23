---
name: ai-traces
status: backlog
created: 2026-05-23T03:55:28Z
updated: 2026-05-23T04:09:51Z
progress: 0%
prd: .claude/prds/ai-traces.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/43
---

# Epic: ai-traces

## Overview

Three additive layers turn the existing `Message` log into a readable admin trace: (1) a backend migration adding per-turn capture fields, (2) a staff-only read API at `/api/admin/conversations/{id}/trace/`, (3) a frontend sibling route at `/admin/ai-traces` with a list and a detail page. Everything is read-only; no agent-behaviour changes.

## Architecture Decisions

- **Additive migration only.** New fields on `Message` are all nullable so historical rows render cleanly and pre-existing tests don't need refixturing.
- **Single trace endpoint.** One `GET /api/admin/conversations/{id}/trace/` serializer aggregates everything the detail page needs — no N+1 fetches from the frontend.
- **Sibling admin route, not embedded.** The existing `/admin` dashboard stays focused on operations; traces get their own `/admin/ai-traces` subtree to avoid touching the admin page.tsx (which Streams B and C also extend).
- **Cost as a derived helper, not a column.** `(model_name, tokens_in, tokens_out)` → estimated dollars via a static `MODEL_PRICING` map computed at serialization time. Easy to update without a migration.

## Technical Approach

### Frontend Components
- `frontend/src/app/admin/ai-traces/page.tsx` — list view (table of conversations newest-first).
- `frontend/src/app/admin/ai-traces/[id]/page.tsx` — detail view (turn-by-turn).
- `frontend/src/components/trace-step.tsx` — one renderable step (user / assistant / tool call / tool result), with collapsible RAG chunks.
- Reuse existing `pd-*` styles; no new CSS file.

### Backend Services
- `backend/core/migrations/000X_message_trace_metadata.py` — adds `latency_ms`, `tokens_in`, `tokens_out`, `model_name`, `prompt_version`, `retrieval_chunk_ids` (JSONB).
- `backend/agent/loop.py` — populates the fields on every `Message` write.
- `backend/api/admin_traces.py` — new DRF view + serializer for the trace endpoint.
- `backend/agent/pricing.py` — pure-function `estimate_cost(model_name, tokens_in, tokens_out) -> float`.

### Infrastructure
- No new services. No environment-variable changes. Static `MODEL_PRICING` dict in code.

## Implementation Strategy

Three task layers, each landing as its own commit on the same epic branch:

1. **Schema + capture** — migration + agent-loop instrumentation. Tests assert the new fields are populated on every assistant turn.
2. **Read API** — endpoint + serializer + permission gate. Tests exercise the JSON shape and the staff-only gate.
3. **Frontend** — list + detail pages. Playwright covers the happy path (open list → click row → see turns).

## Task Breakdown Preview

- 001 — Migration: add trace-metadata fields to Message
- 002 — Agent-loop capture: populate latency / tokens / model / prompt_version / chunk_ids on every Message write
- 003 — Trace API: GET /api/admin/conversations/{id}/trace/ + serializer + tests
- 004 — Frontend list page: /admin/ai-traces
- 005 — Frontend detail page: /admin/ai-traces/[id] with collapsible RAG chunks
- 006 — Cost helper + cost columns in list and detail

## Dependencies

- No cross-stream dependencies on entry. Lands first.
- Stream B reads `prompt_version` once both are in main.
- Stream C reads `model_name`, `tokens_*`, `latency_ms` for aggregates.

## Success Criteria (Technical)

- Migration applies cleanly forward and reverse.
- Trace endpoint p95 latency <300ms for a 50-message conversation.
- Frontend pages render at all from a clean `npm run build`.
- All 154 existing backend tests pass plus ≥6 new tests covering the capture, API, and serializer.

## Estimated Effort

- ~3 days of focused work for one developer.
- Tasks 001 → 002 are sequential (capture needs the columns).
- Tasks 003 / 004 / 005 / 006 can run partially in parallel once 002 is in.

## Tasks Created
- [ ] 001.md - Migration — add trace-metadata fields to Message (parallel: false)
- [ ] 002.md - Agent-loop capture — populate trace fields on every Message write (parallel: true)
- [ ] 003.md - Trace API — GET /api/admin/conversations/{id}/trace/ (parallel: true)
- [ ] 004.md - Frontend list page — /admin/ai-traces (parallel: true)
- [ ] 005.md - Frontend detail page — /admin/ai-traces/[id] (parallel: true)
- [ ] 006.md - Cost helper — agent/pricing.py + cost columns wired (parallel: true)

Total tasks: 6
Parallel tasks: 5
Sequential tasks: 1
Estimated total effort: 18 hours
