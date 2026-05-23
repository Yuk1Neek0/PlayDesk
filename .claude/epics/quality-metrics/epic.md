---
name: quality-metrics
status: backlog
created: 2026-05-23T03:55:28Z
updated: 2026-05-23T04:10:23Z
progress: 0%
prd: .claude/prds/quality-metrics.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/56
---

# Epic: quality-metrics

## Overview

Two parallel deliverables: a CLI-generated `docs/reports/ai-quality-report.md` from the eval set + recent trace data, and a small `/api/admin/metrics/` endpoint feeding four admin dashboard cards. Both lean on existing tables; both degrade gracefully when fields from Streams A and B are missing.

## Architecture Decisions

- **Read-only aggregation only.** No model changes, no migrations. All work goes through Django ORM aggregates over `Message`, `Conversation`, `Booking`.
- **Two output surfaces, one shared core.** The same aggregation functions back both the report generator and the live endpoint — one code path, two formatters.
- **Null-safe everywhere.** Every metric tolerates missing Stream A/B fields by labelling `unknown` rather than erroring.
- **CI-friendly offline mode.** A fixture file lets the report regenerate in CI without LLM keys.

## Technical Approach

### Frontend Components
- `frontend/src/components/metric-card.tsx` — single metric card with `label`, `value`, `format`, accepting `null` → renders `—`.
- Top-of-page card strip injected into `frontend/src/app/admin/page.tsx` (a single small additive edit).

### Backend Services
- `backend/api/admin_metrics.py` — DRF view returning the JSON envelope.
- `backend/evals/quality_report.py` — CLI entry point (`python manage.py runscript quality_report` or `python -m evals.quality_report`).
- `backend/evals/aggregates.py` — shared aggregation functions used by both surfaces.
- `backend/evals/fixtures/sample_messages.json` — checked-in fixture for `--offline` mode.

### Infrastructure
- One new committed report file in `docs/reports/`.
- No new env vars; no new pip deps.

## Implementation Strategy

The aggregation core comes first so the two surfaces can be developed in parallel against it.

## Task Breakdown Preview

- 001 — Aggregation core: shared functions in `evals/aggregates.py` with null-safe math + unit tests
- 002 — Metrics endpoint: GET /api/admin/metrics/?days=N + serializer + tests
- 003 — Admin card strip: top-of-page row in /admin with four cards bound to the endpoint
- 004 — Quality report generator: CLI that emits docs/reports/ai-quality-report.md
- 005 — Offline mode + fixture: `--offline` flag + checked-in `sample_messages.json` so CI is deterministic

## Dependencies

- Soft dep on Stream A — uses `Message.latency_ms`, `tokens_*`, `model_name`. Falls back gracefully.
- Soft dep on Stream B — uses `Conversation.status` and `prompt_version`. Falls back to a "single version" report and 0% handoff rate.

## Success Criteria (Technical)

- Endpoint p95 latency <300ms over 10 000 messages.
- Running the report twice produces an identical file.
- All four cards render against the existing seed DB with non-null values.
- Tests: aggregation null-safety (zero conversations, missing fields), endpoint shape, report determinism.

## Estimated Effort

- ~2 days for one developer.
- Tasks 001 → 002 / 004 in parallel → 003 (depends 002) / 005 (depends 004) in parallel.

## Tasks Created
- [ ] 001.md - Aggregation core — shared null-safe functions in evals/aggregates.py (parallel: false)
- [ ] 002.md - Metrics endpoint — GET /api/admin/metrics/ (parallel: true)
- [ ] 003.md - Admin card strip — top-of-page metric row (parallel: true)
- [ ] 004.md - Quality report generator — docs/reports/ai-quality-report.md (parallel: true)
- [ ] 005.md - Offline mode + fixture — CI-deterministic report (parallel: true)

Total tasks: 5
Parallel tasks: 4
Sequential tasks: 1
Estimated total effort: 17 hours
