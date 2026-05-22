import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

import type { SSEEvent } from "@/types/sse-events";

vi.mock("./sse", () => ({ streamMessage: vi.fn() }));

import { streamMessage } from "./sse";
import { useChatStream } from "./useChatStream";

const mockStream = vi.mocked(streamMessage);

beforeEach(() => {
  mockStream.mockReset();
});

/** An async generator that yields the given events, like `streamMessage`. */
function fakeStream(events: SSEEvent[]) {
  return (async function* () {
    for (const event of events) yield event;
  })();
}

const doneEvent: SSEEvent = {
  type: "done",
  data: { message_id: 5, text: "Hello world", booking_id: 9, iteration_count: 2 },
};

describe("useChatStream", () => {
  it("starts idle", () => {
    const { result } = renderHook(() => useChatStream());
    expect(result.current.status).toBe("idle");
    expect(result.current.text).toBe("");
  });

  it("accumulates token deltas and surfaces the done result", async () => {
    mockStream.mockReturnValue(
      fakeStream([
        { type: "token", data: { delta: "Hello " } },
        { type: "token", data: { delta: "world" } },
        doneEvent,
      ]),
    );

    const { result } = renderHook(() => useChatStream());
    await act(async () => {
      await result.current.send(1, "hi");
    });

    expect(result.current.status).toBe("done");
    expect(result.current.text).toBe("Hello world");
    expect(result.current.result?.booking_id).toBe(9);
  });

  it("sets activeTool from a tool_call_start event", async () => {
    mockStream.mockReturnValue(
      fakeStream([
        {
          type: "tool_call_start",
          data: { tool_call_id: "t1", tool_name: "check_availability", arguments: {} },
        },
      ]),
    );

    const { result } = renderHook(() => useChatStream());
    await act(async () => {
      await result.current.send(1, "is it free?");
    });

    expect(result.current.activeTool).toBe("check_availability");
  });

  it("clears activeTool when the tool call ends", async () => {
    mockStream.mockReturnValue(
      fakeStream([
        {
          type: "tool_call_start",
          data: { tool_call_id: "t1", tool_name: "check_availability", arguments: {} },
        },
        {
          type: "tool_call_end",
          data: { tool_call_id: "t1", tool_name: "check_availability", result: {}, error: null },
        },
        doneEvent,
      ]),
    );

    const { result } = renderHook(() => useChatStream());
    await act(async () => {
      await result.current.send(1, "is it free?");
    });

    expect(result.current.activeTool).toBeNull();
    expect(result.current.status).toBe("done");
  });

  it("surfaces a server error event", async () => {
    mockStream.mockReturnValue(
      fakeStream([
        {
          type: "error",
          data: { code: "llm_unavailable", detail: "LLM is down", retryable: true },
        },
      ]),
    );

    const { result } = renderHook(() => useChatStream());
    await act(async () => {
      await result.current.send(1, "hi");
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error?.code).toBe("llm_unavailable");
  });

  it("surfaces a transport failure as a retryable error", async () => {
    mockStream.mockReturnValue(
      (async function* (): AsyncGenerator<SSEEvent> {
        throw new Error("network down");
      })(),
    );

    const { result } = renderHook(() => useChatStream());
    await act(async () => {
      await result.current.send(1, "hi");
    });

    expect(result.current.status).toBe("error");
    expect(result.current.error?.retryable).toBe(true);
  });

  it("reset clears state back to idle", async () => {
    mockStream.mockReturnValue(fakeStream([{ type: "token", data: { delta: "x" } }, doneEvent]));

    const { result } = renderHook(() => useChatStream());
    await act(async () => {
      await result.current.send(1, "hi");
    });
    act(() => {
      result.current.reset();
    });

    expect(result.current.status).toBe("idle");
    expect(result.current.text).toBe("");
  });
});
