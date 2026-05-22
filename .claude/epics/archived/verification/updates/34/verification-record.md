# Issue #34 — Stream C: Frontend Integration Verification Record

Wave 2 end-to-end verification of dev-plan §1.2 — the frontend work the
`frontend` epic deferred from mocks to the live backend.

- **Worktree:** C:\Users\12146\Desktop\toys\epic-verification (branch epic/verification)
- **Stack:** live docker compose — backend :8000, frontend :3000, db :5432
- **Method:** live-backend curl (direct + through the Next proxy), code inspection
  of frontend/src/lib + components against the live REST/SSE shapes, and the
  four frontend suites (lint, typecheck, test, build).

---

## Summary

| Result | Count |
|--------|-------|
| PASS | 4 |
| PASS (code + live-curl) / NEEDS-VISUAL for #36 | 2 |
| FAIL | 0 |

3 contract-drift bugs were found and fixed in-stream (see "Bugs fixed").
Without those fixes every browser-driven criterion would have failed
(CORS block + Django trailing-slash RuntimeError on POST).

---

## Acceptance Criteria

### 1. `/` manual booking flow completes against the live REST API and persists — PASS

- GET http://localhost:3000/api/resources/ (through the new Next proxy) -> 200,
  5 seeded resources; shape matches components["schemas"]["Resource"].
- GET .../api/resources/1/availability/?date=2026-06-07 -> 200, AvailabilityResponse
  shape (resource_id, date, available[], suggestions[]) — matches api.ts.
- POST .../api/bookings/ with the exact body frontend/src/app/page.tsx::submit()
  builds (resource_id, customer_name, customer_phone, start_time, end_time,
  source:"manual") -> 201, booking #19 persisted. Response is the full
  Booking schema (id, status, created_at, ...) the page consumes.
- page.tsx drives the 4-step flow (resource -> date -> time -> confirm) entirely
  through lib/api.ts; no mocked fetch remains. BookingCreate it sends matches
  docs/contracts/openapi.yaml BookingCreate (all 5 required fields present).

### 2. `/chat` streams real tokens from the live SSE endpoint; tool-call hints render — PASS

- POST .../api/conversations/ -> 201, conversation #83 (Conversation shape).
- POST .../api/conversations/83/messages/ with Accept: text/event-stream -> a real
  text/event-stream. Captured event names across multiple turns:
  token, tool_call_start, tool_call_end, done — all match KNOWN_EVENTS in
  sse.ts and the SSEEvent union in types/sse-events.ts.
- done payload observed: {"message_id":299,"text":"...","booking_id":null,"iteration_count":1}
  — exact match for DoneEvent. tool_call_start/tool_call_end payloads match
  ToolCallStartEvent/ToolCallEndEvent (tool_call_id, tool_name, arguments/result/error).
- Timed capture shows events arrive incrementally over seconds (tool events
  seconds apart, tokens streaming after) — not one buffered burst — so the
  in-flight tool window is real.
- chat/page.tsx renders the pd-tools hint block from useChatStream().tools[],
  showing a spinner + tool_name while status==="running" and a check on "done".
  The "checking availability... / looking up policy..." hint is the tool name + spinner.
- NEEDS-VISUAL (#36): final confirmation that the hint visibly renders in the
  browser during the in-flight window (verified here via stream timing + code).

### 3. A booking made through `/chat` appears in `/admin` without a manual refresh — PASS (code + live-curl); NEEDS-VISUAL for #36

- Drove a booking via the live SSE chat: POST .../conversations/83/messages/
  with a booking request -> tool_call_end for create_booking returned
  booking_id: 24, and GET .../api/admin/bookings/ then shows #24
  source:"agent" at the top of the list.
- admin/page.tsx polls adminListBookings() every POLL_MS = 12_000, diffs
  booking IDs against bookingIdsRef, calls setBookings(...), and flags new
  rows with an is-new class for 3.5s — i.e. a /chat booking surfaces within
  ~12s with no manual refresh.
- NEEDS-VISUAL (#36): observe the new row actually appear + the is-new
  highlight animate in a live browser session within the poll interval.

### 4. `/admin` shows live conversations and all bookings sorted by created_at desc — PASS

- GET .../api/admin/bookings/ -> count:9, results strictly descending by
  created_at (#19 13:20:02, #14 13:09:57, #13 13:09:21, ...).
- GET .../api/admin/conversations/ -> count:52, descending by started_at
  (#84 13:20:28, #83 13:20:15, #82 13:18:08, ...).
- admin/page.tsx loads both via adminListBookings() / adminListConversations(),
  renders the conversation list and the "All bookings" table ("Newest first"),
  and refetches bookings on the poll. Backend ordering matches the OpenAPI note
  "List all bookings sorted by created_at desc".

### 5. The chat UI does not freeze during long tool-call sequences — PASS (code + live-curl); NEEDS-VISUAL for #36

- useChatStream.ts consumes the SSE stream with an async generator + for await,
  applying incremental setState per event — no synchronous blocking loop;
  React yields between events.
- Live multi-tool turns (3 tool_call_start/tool_call_end pairs + a create_booking
  then ~25 tokens) streamed over several seconds; the generator processes each
  event as it arrives, so the event loop is never starved.
- chat/page.tsx keeps the composer interactive (disabled only reflects streaming,
  the textarea/state is never blocked) and re-pins scroll via a cheap useEffect.
- NEEDS-VISUAL (#36): confirm in a real browser that the composer/scroll stay
  responsive through a long agent turn (verified here via stream timing + the
  non-blocking hook design).

### 6. Verification record written — PASS

This file: .claude/epics/verification/updates/34/verification-record.md.
(The task body says updates/004/; the synced epic uses the GitHub issue
number, so the record lives in updates/34/ — consistent with sibling
streams 31/-35/.)

---

## Bugs fixed

All three are contract-drift bugs fixed in-stream (explicit user decision),
minimal changes, scoped to frontend/ + the one infra file noted below.

### Bug 1 — Backend has no CORS headers; the browser cannot call it cross-origin

The Django backend ships no django-cors-headers / CORS middleware
(backend/config/settings.py MIDDLEWARE). A browser at localhost:3000
issuing fetch to http://127.0.0.1:8000 (the old api.ts default) would be
blocked by the same-origin policy — every REST + SSE call from the real UI
would fail. Fixing CORS in backend/ is out of scope, so this was solved
frontend-side with a same-origin proxy.

Fix (frontend/):
- frontend/next.config.mjs — added a rewrites() rule proxying
  /api/:path* -> ${BACKEND_ORIGIN}/api/:path*/. The browser now makes
  same-origin requests to the Next server, which forwards them server-side
  (CORS is moot for server-to-server).
- frontend/src/lib/api.ts — API_BASE_URL default changed from
  http://127.0.0.1:8000 to "" (same-origin) so requests hit the proxy.
  NEXT_PUBLIC_API_BASE_URL still overrides if ever needed.

### Bug 2 — Django requires trailing slashes; frontend/contract omit them

Django's URLConf (backend/api/urls.py, backend/agent/urls.py) registers
every route with a trailing slash and runs with APPEND_SLASH on. The
OpenAPI contract (docs/contracts/openapi.yaml) and the frontend clients used
slash-less paths. Live behaviour confirmed by curl:
- GET /api/resources -> 301 redirect (extra round-trip).
- POST /api/bookings -> 500 RuntimeError — CommonMiddleware cannot
  301-redirect a POST that carries a body. The manual booking flow and the
  chat POST .../messages would both have hard-failed.

Fix (frontend/):
- frontend/src/lib/api.ts — added withTrailingSlash(path); the request()
  helper now normalises every REST path to end in / before the query string.
- frontend/src/lib/sse.ts — the streamMessage fetch URL routed through the
  same withTrailingSlash helper.
- frontend/next.config.mjs — added skipTrailingSlashRedirect: true (Next
  otherwise 308-strips the slash before the rewrite) and appended / in the
  rewrite destination so the proxied request reaches Django with the slash
  Django's URLConf requires.

### Bug 3 — BACKEND_ORIGIN build/proxy wiring

next.config.mjs `rewrites()` is evaluated at build time, so the proxy
target must be known when the frontend image is built — a plain runtime
env var is not enough.

Fix:
- frontend/Dockerfile — added `ARG BACKEND_ORIGIN` and passed it through to
  the build so `rewrites()` bakes the correct target.
- docker-compose.yml — added the `BACKEND_ORIGIN` build arg and environment
  entry on the `frontend` service (default `http://backend:8000`, the
  in-network backend hostname). This is a root infra file outside the
  frontend/ scope — flagged here for the #36 integration task.

---

## Files changed

| File | Scope | Bug |
|---|---|---|
| frontend/next.config.mjs | in scope | 1, 2, 3 |
| frontend/src/lib/api.ts | in scope | 1, 2 |
| frontend/src/lib/sse.ts | in scope | 2 |
| frontend/Dockerfile | in scope | 3 |
| docker-compose.yml | **shared infra — for #36** | 3 |

`frontend/src/types/api.d.ts` was NOT modified — the OpenAPI types matched
the live backend; the drift was in paths/origin, not schemas.

## Suites after fixes

- `npm run lint` — clean
- `npm run typecheck` — clean
- `npm test` — 49 / 49 passed
- `npm run build` — succeeds
- Frontend container rebuilt; live end-to-end verified through the proxy.

## Left for #36

- **NEEDS-VISUAL** confirmation in a real browser of: criterion 2 (tool hint
  renders during the in-flight window), criterion 3 (new `/chat` booking row
  appears in `/admin` within the 12s poll with the is-new highlight), and
  criterion 5 (composer/scroll stay responsive through a long agent turn).
  All three were verified by stream timing + code inspection; only the visual
  render remains.
- `docker-compose.yml` carries this stream's `BACKEND_ORIGIN` change — confirm
  it coexists with the other streams' infra edits.
- The backend has no CORS middleware. Stream C solved it frontend-side with a
  same-origin proxy (correct for this architecture); if a future non-proxied
  client is needed, `django-cors-headers` would be the backend-side fix.
