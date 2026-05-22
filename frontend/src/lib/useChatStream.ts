"use client";

// React hook over `streamMessage` — drives the chat UI without blocking it.
//
// Tokens accumulate into `text` as they arrive; `activeTool` reflects the
// in-flight tool call (or null) so the UI can show a "checking…" hint. State
// updates are incremental, so React stays responsive through long tool-call
// sequences.

import { useCallback, useRef, useState } from "react";

import { streamMessage } from "./sse";
import type { DoneEvent, StreamErrorEvent } from "@/types/sse-events";

export type ChatStreamStatus = "idle" | "streaming" | "done" | "error";

export interface ChatStreamState {
  status: ChatStreamStatus;
  /** Assistant text accumulated from `token` events. */
  text: string;
  /** `tool_name` of the running tool call, or null when none is in flight. */
  activeTool: string | null;
  /** Payload of the terminal `done` event, once received. */
  result: DoneEvent | null;
  /** Payload of a terminal `error` event or a transport failure. */
  error: StreamErrorEvent | null;
}

const INITIAL_STATE: ChatStreamState = {
  status: "idle",
  text: "",
  activeTool: null,
  result: null,
  error: null,
};

export interface ChatStream extends ChatStreamState {
  /** Send a user message and stream the assistant response. */
  send: (conversationId: number, content: string) => Promise<void>;
  /** Abort any in-flight stream and clear state back to idle. */
  reset: () => void;
}

export function useChatStream(): ChatStream {
  const [state, setState] = useState<ChatStreamState>(INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (conversationId: number, content: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setState({ ...INITIAL_STATE, status: "streaming" });

      try {
        for await (const event of streamMessage(
          conversationId,
          content,
          controller.signal,
        )) {
          if (controller.signal.aborted) return;
          switch (event.type) {
            case "token":
              setState((s) => ({ ...s, text: s.text + event.data.delta }));
              break;
            case "tool_call_start":
              setState((s) => ({ ...s, activeTool: event.data.tool_name }));
              break;
            case "tool_call_end":
              setState((s) => ({ ...s, activeTool: null }));
              break;
            case "done":
              setState((s) => ({
                ...s,
                status: "done",
                activeTool: null,
                result: event.data,
                // `done.text` is the canonical assembled response.
                text: event.data.text || s.text,
              }));
              break;
            case "error":
              setState((s) => ({
                ...s,
                status: "error",
                activeTool: null,
                error: event.data,
              }));
              break;
          }
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setState((s) => ({
          ...s,
          status: "error",
          activeTool: null,
          error: {
            code: "stream_failed",
            detail:
              err instanceof Error
                ? err.message
                : "The connection to the assistant failed.",
            retryable: true,
          },
        }));
      }
    },
    [],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setState(INITIAL_STATE);
  }, []);

  return { ...state, send, reset };
}
