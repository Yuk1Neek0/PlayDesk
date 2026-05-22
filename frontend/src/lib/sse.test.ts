import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { parseSSEEvent, streamMessage } from "./sse";
import type { SSEEvent } from "@/types/sse-events";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Build a streamed `text/event-stream` Response from raw chunks. */
function sseResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

async function collect(conversationId: number, content: string): Promise<SSEEvent[]> {
  const events: SSEEvent[] = [];
  for await (const event of streamMessage(conversationId, content)) {
    events.push(event);
  }
  return events;
}

describe("parseSSEEvent", () => {
  it("parses a token event", () => {
    expect(parseSSEEvent('event: token\ndata: {"delta":"Hi"}')).toEqual({
      type: "token",
      data: { delta: "Hi" },
    });
  });

  it("parses a done event", () => {
    const block =
      'event: done\ndata: {"message_id":42,"text":"Done","booking_id":17,"iteration_count":2}';
    expect(parseSSEEvent(block)).toEqual({
      type: "done",
      data: { message_id: 42, text: "Done", booking_id: 17, iteration_count: 2 },
    });
  });

  it("ignores SSE comment lines", () => {
    expect(parseSSEEvent(': keep-alive\nevent: token\ndata: {"delta":"x"}')).toEqual({
      type: "token",
      data: { delta: "x" },
    });
  });

  it("returns null for an unknown event name", () => {
    expect(parseSSEEvent("event: heartbeat\ndata: {}")).toBeNull();
  });

  it("returns null for unparseable JSON", () => {
    expect(parseSSEEvent('event: token\ndata: {oops')).toBeNull();
  });

  it("returns null when the data line is missing", () => {
    expect(parseSSEEvent("event: token")).toBeNull();
  });
});

describe("streamMessage", () => {
  it("yields each parsed event from the stream in order", async () => {
    fetchMock.mockResolvedValue(
      sseResponse([
        'event: token\ndata: {"delta":"Sure "}\n\n',
        'event: tool_call_start\ndata: {"tool_call_id":"tc_1","tool_name":"check_availability","arguments":{}}\n\n',
        'event: tool_call_end\ndata: {"tool_call_id":"tc_1","tool_name":"check_availability","result":{},"error":null}\n\n',
        'event: done\ndata: {"message_id":1,"text":"Sure thing","booking_id":null,"iteration_count":1}\n\n',
      ]),
    );

    const events = await collect(7, "hello");

    expect(events.map((e) => e.type)).toEqual([
      "token",
      "tool_call_start",
      "tool_call_end",
      "done",
    ]);
  });

  it("POSTs the message to the conversation's stream endpoint", async () => {
    fetchMock.mockResolvedValue(
      sseResponse(['event: done\ndata: {"message_id":1,"text":"","booking_id":null,"iteration_count":1}\n\n']),
    );

    await collect(9, "book me a room");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/conversations/9/messages");
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      content: "book me a room",
    });
  });

  it("reassembles events split across stream chunks", async () => {
    fetchMock.mockResolvedValue(
      sseResponse(["event: tok", 'en\ndata: {"de', 'lta":"x"}\n\n']),
    );

    expect(await collect(1, "hi")).toEqual([{ type: "token", data: { delta: "x" } }]);
  });

  it("handles CRLF event framing", async () => {
    fetchMock.mockResolvedValue(
      sseResponse(['event: token\r\ndata: {"delta":"y"}\r\n\r\n']),
    );

    expect(await collect(1, "hi")).toEqual([{ type: "token", data: { delta: "y" } }]);
  });

  it("flushes a trailing event with no closing blank line", async () => {
    fetchMock.mockResolvedValue(
      sseResponse(['event: token\ndata: {"delta":"tail"}']),
    );

    expect(await collect(1, "hi")).toEqual([{ type: "token", data: { delta: "tail" } }]);
  });

  it("throws ApiError on a non-OK response", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "no such conversation" }), { status: 404 }),
    );

    await expect(collect(404, "hi")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });
});
