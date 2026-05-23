---
name: quality-metrics
description: Turn the existing eval suite plus per-turn trace metadata into an aggregate AI-quality report and a business-metrics strip on the admin dashboard.
status: backlog
created: 2026-05-23T03:55:28Z
---

# PRD: quality-metrics

## Executive Summary

PlayDesk already has an eval suite (per-case pass/fail) and — once Stream A lands — per-turn latency, cost, model, and prompt-version metadata. This epic turns both into two outputs:

1. A generated `docs/reports/ai-quality-report.md` summarising eval pass-rate by prompt version, RAG-vs-SQL routing accuracy, average latency, average cost, and handoff rate.
2. A small set of admin endpoints + dashboard cards that surface the same metrics live from real conversations: AI booking conversion, handoff rate, average response time, estimated front-desk time saved, AI-created revenue estimate.

This stream is the most parallelizable because most of its work is read-only aggregation over existing tables.

## Problem Statement

Prompt iteration today is a guess: change the string, run the demo, decide whether it "felt better". There is no aggregate signal. Equally, the demo's pitch — that an AI front desk converts conversations into bookings and saves staff time — has no numbers to back it up at the dashboard level. A reviewer asking "what's the business case?" gets an arm-wave.

## User Stories

- **As a developer**, I can run a single command and get a markdown report comparing prompt versions on the same eval set.
  - *Acceptance:* the report lists each prompt version with tool-selection accuracy, RAG accuracy, booking safety, average latency, average cost; at least two versions are compared; one improvement decision is recorded inline.
- **As a reviewer demoing PlayDesk**, I can open `/admin` and immediately see four cards: AI booking conversion %, handoff rate %, average AI response time, estimated revenue assisted by AI.
  - *Acceptance:* all four cards render with non-null values when the DB has at least one AI booking, otherwise they show a clean `—` rather than blowing up.
- **As staff**, I can filter the bookings table by `source = agent` vs `source = manual` to see which channel drove which bookings.
  - *Acceptance:* the existing source-filter already exists; this stream verifies it stays correct and adds the source split into the metrics card row.

## Functional Requirements

1. **`backend/evals/quality_report.py`** — CLI entry point that:
   - replays the existing eval set against the live agent (or against a recorded fixture for CI),
   - aggregates results by `prompt_version` and `model_name`,
   - cross-joins with the last N days of `Message` rows to add real-world latency / cost,
   - emits `docs/reports/ai-quality-report.md` with a per-version table and a "what changed and why" footer.
2. **Business-metrics endpoint** — `GET /api/admin/metrics/` returning JSON:
   - `ai_booking_conversion`: AI conversations that resulted in a confirmed booking / all AI conversations
   - `handoff_rate`: conversations with `status in (needs_human, staff_takeover)` / all conversations
   - `avg_response_time_ms`: mean of `Message.latency_ms` over the last 7 days for assistant turns
   - `est_revenue_assisted`: sum of `Booking.resource.price_per_hour * hours` for AI-sourced bookings
   - `bookings_by_source`: `{ agent: N, manual: N }`
   - All keys nullable when the underlying data is missing.
3. **Admin metric cards** — a new top-of-page card row in `/admin/page.tsx` showing the four cards. Cards must accept `value: number | null` and render `—` on null with the label still visible.
4. **Daily-window filter** — endpoint accepts `?days=7` (default) so different views can request different windows.
5. **CI-friendly mode** — `quality_report.py --offline` reads from a checked-in fixture (`backend/evals/fixtures/sample_messages.json`) so CI can produce a deterministic report without hitting an LLM.

## Non-Functional Requirements

- Endpoint must respond <300ms with up to 10 000 messages in the table — single aggregate query, no N+1.
- Report generator is idempotent — running twice produces the same file.
- Cards must render before the metrics fetch resolves (skeleton state).
- All math handles "zero conversations" cleanly — no divide-by-zero, no NaN in the JSON.

## Success Criteria

- `python manage.py runscript quality_report` produces `docs/reports/ai-quality-report.md` on first run.
- The report compares ≥2 prompt versions when at least two `prompt_version` values exist in the DB.
- Admin loads with all four cards populated against the seed data.
- A reviewer can answer "did v2_strict_tools improve over v1_basic?" by pointing at the report — no manual eyeballing.

## Constraints & Assumptions

- Lands cleanly without Stream B's `prompt_version` — the aggregator groups by `prompt_version=NULL` and labels it `unknown` in that mode.
- Pricing constants are hard-coded (no live Stripe lookups for `est_revenue_assisted`).

## Out of Scope

- Live alerting on metric regressions (Slack / email).
- Multi-store rollups.
- Per-customer cohort analysis.

## Dependencies

- Soft dep on Stream A — uses `Message.latency_ms`, `tokens_*`, `model_name`. Falls back to wall-time estimates and "unknown" cost when fields are missing.
- Soft dep on Stream B — uses `Conversation.status` for handoff rate, `prompt_version` for prompt comparison. Falls back to "0%" handoff rate and "single version" when missing.
