// SSE reader for the streaming chat endpoint.
//
// `POST /api/conversations/{id}/messages` returns `text/event-stream`.
// `EventSource` cannot send a POST body, so we use `fetch` + the response
// `ReadableStream` and parse the W3C SSE framing ourselves.

import { API_BASE_URL, ApiError, withTrailingSlash } from "./api";
import type { SSEEvent } from "@/types/sse-events";

const KNOWN_EVENTS = new Set([
  "token",
  "tool_call_start",
  "tool_call_end",
  "done",
  "error",
]);

/**
 * Parse a single SSE event block (the text between blank-line delimiters)
 * into a typed `SSEEvent`. Returns `null` for blocks with an unknown event
 * name, missing data, or unparseable JSON — callers skip those.
 */
export function parseSSEEvent(block: string): SSEEvent | null {
  let eventName = "";
  const dataLines: string[] = [];

  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // SSE comment
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }

  if (!KNOWN_EVENTS.has(eventName) || dataLines.length === 0) return null;

  try {
    const data = JSON.parse(dataLines.join("\n"));
    return { type: eventName, data } as SSEEvent;
  } catch {
    return null;
  }
}

/**
 * POST a user message and yield each parsed SSE event as it arrives.
 *
 * The generator completes when the stream closes (normally after a `done` or
 * `error` event). Pass an `AbortSignal` to cancel an in-flight stream.
 */
export async function* streamMessage(
  conversationId: number,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const response = await fetch(
    `${API_BASE_URL}${withTrailingSlash(
      `/api/conversations/${conversationId}/messages`,
    )}`,
    {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ content }),
      signal,
    },
  );

  if (!response.ok || !response.body) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // Leave as null.
    }
    throw new ApiError(response.status, body);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      // Normalise CRLF so a single `\n\n` split handles W3C and the
      // contract's plain-`\n` framing alike.
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      let delimiter = buffer.indexOf("\n\n");
      while (delimiter !== -1) {
        const block = buffer.slice(0, delimiter);
        buffer = buffer.slice(delimiter + 2);
        const event = parseSSEEvent(block);
        if (event) yield event;
        delimiter = buffer.indexOf("\n\n");
      }
    }

    // Flush a trailing event that arrived without its closing blank line.
    const tail = parseSSEEvent(buffer);
    if (tail) yield tail;
  } finally {
    reader.releaseLock();
  }
}
