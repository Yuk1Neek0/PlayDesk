# PlayDesk SSE Protocol

The `POST /api/conversations/{id}/messages` endpoint returns a
**Server-Sent Events** (SSE) stream with `Content-Type: text/event-stream`.

The stream follows the W3C SSE specification: each event is a block of lines
ending with a blank line. Every event carries an explicit `event:` name and a
single `data:` line containing a JSON object.

---

## Connection lifecycle

```
Client                          Server
  |                               |
  |  POST /api/conversations/N/messages   |
  |------------------------------>|
  |                               |  (agent loop starts)
  |    event: token               |
  |<------------------------------|
  |    event: tool_call_start     |
  |<------------------------------|
  |    event: token               |
  |<------------------------------|
  |    event: tool_call_end       |
  |<------------------------------|
  |    …more tokens…              |
  |<------------------------------|
  |    event: done                |
  |<------------------------------|
  |  (stream closes)              |
```

---

## Event types

### `token`

Emitted for each text token produced by the LLM. The client appends `delta`
to its in-progress assistant message buffer.

```
event: token
data: {"delta": "Sure! Let me check availability…"}
```

| Field | Type | Description |
|-------|------|-------------|
| `delta` | `string` | The incremental token text (may be multiple words) |

---

### `tool_call_start`

Emitted when the agent begins executing a tool call. The frontend uses this
to show a "checking…" hint in the chat UI.

```
event: tool_call_start
data: {"tool_call_id": "tc_01", "tool_name": "check_availability", "arguments": {"resource_type": "console", "date": "2026-06-07", "time_range": {"start": "20:00", "end": "22:00"}, "party_size": 2}}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool_call_id` | `string` | Opaque ID matching the LLM's tool-call request; also echoed in `tool_call_end` |
| `tool_name` | `string` | One of the registered agent tools (see §1.5 of the dev plan) |
| `arguments` | `object` | The parsed arguments passed to the tool (mirrors the Pydantic schema) |

---

### `tool_call_end`

Emitted when the tool returns. The `result` field is the raw tool return value.

```
event: tool_call_end
data: {"tool_call_id": "tc_01", "tool_name": "check_availability", "result": {"available": [{"start": "2026-06-07T20:00:00+08:00", "end": "2026-06-07T22:00:00+08:00"}], "suggestions": []}, "error": null}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool_call_id` | `string` | Matches the corresponding `tool_call_start` |
| `tool_name` | `string` | Name of the tool that was called |
| `result` | `object \| null` | Serialised return value; `null` when `error` is non-null |
| `error` | `string \| null` | Error message if the tool raised; `null` on success |

---

### `done`

Emitted once as the final event, immediately before the server closes the
stream. Contains the complete assembled assistant text and any booking created
during this turn.

```
event: done
data: {"message_id": 42, "text": "I've booked PS5 Station A for you on Saturday 8–10 pm. Your booking ID is 17.", "booking_id": 17, "iteration_count": 2}
```

| Field | Type | Description |
|-------|------|-------------|
| `message_id` | `integer` | ID of the persisted `Message` row for the assistant turn |
| `text` | `string` | Full assembled assistant response text |
| `booking_id` | `integer \| null` | ID of the booking created this turn, or `null` |
| `iteration_count` | `integer` | Number of agent loop iterations used (max 6) |

---

### `error`

Emitted when the agent loop encounters an unrecoverable error (e.g., LLM API
failure after retries, iteration limit reached without graceful fallback).
The stream closes immediately after this event.

```
event: error
data: {"code": "llm_unavailable", "detail": "LLM API unavailable after 3 retries. Please try again shortly.", "retryable": true}
```

| Field | Type | Description |
|-------|------|-------------|
| `code` | `string` | Machine-readable error code (see table below) |
| `detail` | `string` | Human-readable message safe to display to the user |
| `retryable` | `boolean` | `true` if the client should offer a retry button |

**Error codes:**

| Code | Trigger |
|------|---------|
| `llm_unavailable` | LLM API failed after 3 exponential-backoff retries |
| `iteration_limit` | Agent hit the 6-iteration hard cap without completing |
| `tool_failure` | A critical tool raised an exception the LLM could not recover from |
| `conversation_not_found` | The conversation ID does not exist |
| `invalid_message` | Request body failed validation |

---

## Client implementation notes

1. Use the browser's `EventSource` API or `fetch` + `ReadableStream` to
   consume the stream.  
   `EventSource` does not support `POST` bodies; use a `fetch`-based SSE
   reader (e.g., `@microsoft/fetch-event-source`) for the message endpoint.

2. Concatenate `token.delta` values in order to reconstruct the full
   assistant text. The `done.text` field provides the canonical assembled
   version for persistence / display.

3. On `tool_call_start`, display an inline hint such as
   *"Checking availability…"* or *"Looking up policy…"* using `tool_name`
   as the discriminator.

4. On `error`, show `detail` to the user and use `retryable` to decide
   whether to render a retry button.

5. Always listen for the `done` event to confirm the stream completed
   normally before marking the message as delivered.

---

## TypeScript type generation

Types for the REST endpoints in `openapi.yaml` are generated with:

```bash
npx openapi-typescript docs/contracts/openapi.yaml \
  --output frontend/src/types/api.d.ts
```

This produces typed `paths` and `components` exports. Import as:

```typescript
import type { components, paths } from "@/types/api";

type Booking = components["schemas"]["Booking"];
type CreateBookingBody =
  paths["/api/bookings/"]["post"]["requestBody"]["content"]["application/json"];
```

SSE event payload types (not in the OpenAPI spec, since SSE is not a standard
OpenAPI response type) are maintained in
`frontend/src/types/sse-events.ts` and kept manually in sync with this document:

```typescript
export interface TokenEvent {
  delta: string;
}
export interface ToolCallStartEvent {
  tool_call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}
export interface ToolCallEndEvent {
  tool_call_id: string;
  tool_name: string;
  result: unknown | null;
  error: string | null;
}
export interface DoneEvent {
  message_id: number;
  text: string;
  booking_id: number | null;
  iteration_count: number;
}
export interface ErrorEvent {
  code: string;
  detail: string;
  retryable: boolean;
}
```
