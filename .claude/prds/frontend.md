---
name: frontend
description: Wire the PlayDesk frontend to the real backend — manual booking flow, streaming AI chat, and the staff dashboard.
status: backlog
created: 2026-05-21T19:51:40Z
---

# PRD: frontend

## Executive Summary

The `frontend` epic turns the foundation's static page shells into the working product UI: a manual booking flow, a streaming AI front-desk chat, and a staff dashboard — all wired to the backend-core REST API and SSE endpoint via the OpenAPI-generated types.

## Problem Statement

Foundation shipped `/`, `/chat`, and `/admin` as placeholder shells. They render nothing real. This epic connects them to live data so a customer can actually book — manually or by chat — and staff can watch it happen.

## User Stories

- **As a customer**, I can complete a booking through `/` (resource → date → time → confirm) against real availability.
- **As a customer**, I can book through `/chat` by conversation, watching assistant tokens stream in with "checking availability…" / "looking up policy…" hints during tool calls.
  - *Acceptance:* the chat UI never freezes during long tool-call sequences.
- **As staff**, I see live conversations and all bookings (newest first) on `/admin`, and a booking made via `/chat` appears there without a manual refresh.

## Functional Requirements

1. **Typed API client** — generated from `docs/contracts/openapi.yaml`.
2. **Manual booking page** (`/`) — resource picker, date, available-slot selection, confirmation; calls the real availability + booking endpoints.
3. **Chat page** (`/chat`) — consumes the SSE stream per `docs/contracts/sse-protocol.md`; renders streaming tokens and in-flight tool-call hints.
4. **Admin dashboard** (`/admin`) — live conversations view + bookings list sorted by `created_at` desc; auto-updates.

## Non-Functional Requirements

- Page UIs come from Claude Design (Anthropic Labs) handoff exports integrated into the repo; dummy auth retained.
- Builds and tests pass against mocked API responses (CI has no live backend).
- The UI stays responsive during streaming and tool-call sequences.

## Success Criteria

- A user completes a full booking through `/chat` and it appears in `/admin` without refresh.
- CI green: lint, typecheck, vitest, build.

## Constraints & Assumptions

- Builds against the frozen OpenAPI + SSE contracts; end-to-end verification against a live backend is Wave 2 integration.
- Next.js App Router; no custom design system.

## Out of Scope

- Backend logic (`backend-core`); Stripe checkout UI and bilingual UX (`enhancements`).

## Dependencies

- Frozen `foundation` contracts (OpenAPI, SSE). Can build concurrently with `backend-core`; full end-to-end check follows backend-core merge.
