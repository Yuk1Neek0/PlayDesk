---
name: frontend
status: completed
created: 2026-05-21T19:51:40Z
progress: 100%
prd: .claude/prds/frontend.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/18
---

# Epic: frontend

## Overview

Wire the foundation's static `/`, `/chat`, and `/admin` shells to the real backend via the OpenAPI-generated client and the SSE stream. All work is under `frontend/` — fully concurrent with `backend-core`.

## Architecture Decisions

- **Generated API client.** TypeScript types generated from `docs/contracts/openapi.yaml`; no hand-written request/response types.
- **Build against mocks.** Components are tested against mocked fetch/SSE so CI needs no live backend; end-to-end verification is Wave 2.
- **SSE via a typed reader.** A small client reads the SSE protocol's event types and exposes tokens + tool-call hints to React.
- **Page UIs from Claude Design.** The `/`, `/chat`, and `/admin` UIs are produced in Claude Design (Anthropic Labs) and exported into the repo; tasks #20–#22 wire the exported markup/components to live data rather than hand-rolling Tailwind. Task #19 (data layer) has no UI and is unaffected.

## Technical Approach

### Frontend Components
- **`/`** — resource picker → date → live availability slots → confirm; calls availability + booking endpoints.
- **`/chat`** — message composer + transcript; consumes SSE, renders streaming tokens and in-flight tool-call hints; non-blocking during tool calls.
- **`/admin`** — live conversations panel + bookings table (newest first); polling or refetch so new bookings appear without manual refresh.
- Shared: generated API client, SSE client hook, fetch wrappers.

## Implementation Strategy

A single `frontend/` stream — can run as one agent, or split per page once the shared API/SSE client lands. Concurrent with `backend-core`.

## Task Breakdown Preview

- **001** API client & SSE hook — generated types + typed fetch + SSE reader.
- **002** Manual booking page — `/` wired to availability + booking.
- **003** Chat page — `/chat` streaming UI.
- **004** Admin dashboard — `/admin` live conversations + bookings.

## Dependencies

- Frozen `foundation` contracts (OpenAPI, SSE). End-to-end check follows `backend-core` merge.
- Claude Design handoff exports for the three pages — #20–#22 are blocked until the exports land in the repo. #19 has no such dependency.

## Success Criteria (Technical)

- A full booking can be completed through `/chat` and shows in `/admin` without refresh (verified end-to-end in Wave 2).
- CI green: lint, typecheck, vitest, build.

## Estimated Effort

- ~12h total; ~6h wall-clock if split per page after the shared client lands.

## Tasks Created
- [ ] #19 - API client & SSE hook (parallel: true)
- [ ] #20 - Manual booking page (parallel: true, depends on #19)
- [ ] #21 - Chat page (parallel: true, depends on #19)
- [ ] #22 - Admin dashboard (parallel: true, depends on #19)

Total tasks: 4
Parallel tasks: 4
Sequential tasks: 0
Estimated total effort: 12 hours
