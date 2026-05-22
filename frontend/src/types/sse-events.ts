// SSE event payload types for `POST /api/conversations/{id}/messages`.
// Kept manually in sync with docs/contracts/sse-protocol.md — SSE is not an
// OpenAPI response type, so these are not part of the generated `api.d.ts`.

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

// Named `StreamErrorEvent` to avoid clashing with the DOM `ErrorEvent` global.
export interface StreamErrorEvent {
  code: string;
  detail: string;
  retryable: boolean;
}

// Discriminated union of every parsed SSE event, tagged by its `event:` name.
export type SSEEvent =
  | { type: "token"; data: TokenEvent }
  | { type: "tool_call_start"; data: ToolCallStartEvent }
  | { type: "tool_call_end"; data: ToolCallEndEvent }
  | { type: "done"; data: DoneEvent }
  | { type: "error"; data: StreamErrorEvent };
