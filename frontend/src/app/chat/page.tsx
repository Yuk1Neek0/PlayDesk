"use client";

// AI front-desk chat — UI ported from the Claude Design handoff, wired to the
// live backend: a conversation is created via the REST client and the
// assistant response is consumed from the real SSE stream through the
// useChatStream hook (#19). Streaming tokens and in-flight tool-call hints
// render as they arrive; the composer never blocks. This completes task #21.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { Icon } from "@/components/pd-ui";
import { createConversation } from "@/lib/api";
import { useChatStream, type ToolHint } from "@/lib/useChatStream";

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  tools: ToolHint[];
  /** booking_id from the stream's `done` event, when a booking was made. */
  booking: number | null;
}

const SUGGESTIONS = [
  "Is the PS5 free Saturday 8 pm?",
  "Book the Switch for 4 people",
  "What board games do you have?",
  "How late are you open?",
];

const GREETING =
  "Hi — I'm the PlayDesk front desk. I can check availability, answer " +
  "questions about consoles, rooms or board games, and finish a booking " +
  "with you in a single chat. What are we doing tonight?";

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>(() => [
    { id: 1, role: "assistant", content: GREETING, tools: [], booking: null },
  ]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const idRef = useRef(2);
  // Guards the window between a send starting and the stream taking over,
  // so a fast double-send can't create two conversations.
  const busyRef = useRef(false);

  const { status, text, tokens, tools, result, error, send: streamSend } = useChatStream();
  const streaming = status === "streaming";

  // Re-pin the transcript to the bottom as it grows or the stream advances.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && (messages.length || text || status)) el.scrollTop = el.scrollHeight;
  }, [messages, text, status]);

  function nextId() {
    return idRef.current++;
  }

  async function send(raw: string) {
    const content = raw.trim();
    if (!content || streaming || busyRef.current) return;
    busyRef.current = true;

    // The previous assistant turn (if any) is finished — commit it to history
    // before the hook is reset by the next stream.
    const carried: Message[] =
      status === "done" && result
        ? [
            {
              id: nextId(),
              role: "assistant",
              content: result.text,
              tools,
              booking: result.booking_id,
            },
          ]
        : [];
    const userMsg: Message = { id: nextId(), role: "user", content, tools: [], booking: null };
    setMessages((m) => [...m, ...carried, userMsg]);
    setInput("");

    let cid = conversationId;
    if (cid === null) {
      try {
        cid = (await createConversation()).id;
        setConversationId(cid);
      } catch {
        setMessages((m) => [
          ...m,
          {
            id: nextId(),
            role: "assistant",
            content: "Sorry — I couldn't start a session just now. Please try again.",
            tools: [],
            booking: null,
          },
        ]);
        busyRef.current = false;
        return;
      }
    }
    streamSend(cid, content);
    busyRef.current = false;
  }

  function retry() {
    if (conversationId === null) return;
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (lastUser) streamSend(conversationId, lastUser.content);
  }

  // The in-flight / just-finished assistant turn, rendered live from the hook.
  const showLive = (status === "streaming" || status === "done") && (text || tools.length > 0);

  return (
    <div className="pd-page pd-page--chat">
      <header className="pd-chat-head">
        <div className="pd-chat-head-l">
          <div className="pd-avatar pd-avatar--ai" aria-hidden>
            <Icon.spark size={16} />
          </div>
          <div>
            <h1 className="pd-chat-title">PlayDesk Front Desk</h1>
            <div className="pd-chat-meta">
              <span className="pd-pulse" /> Online · usually replies in seconds
            </div>
          </div>
        </div>
        <Link className="pd-link" href="/">
          Prefer to book manually →
        </Link>
      </header>

      <div className="pd-chat-transcript" ref={scrollRef}>
        {messages.map((m) => (
          <Bubble
            key={m.id}
            role={m.role}
            content={m.content}
            tools={m.tools}
            booking={m.booking}
            streaming={false}
          />
        ))}
        {showLive && (
          <Bubble
            role="assistant"
            content={text}
            tokens={streaming ? tokens : undefined}
            tools={tools}
            booking={status === "done" ? result?.booking_id ?? null : null}
            streaming={streaming}
          />
        )}
        {streaming && !text && tools.length === 0 && (
          <div className="pd-chat-typing-row">
            <div className="pd-avatar pd-avatar--ai pd-avatar--sm" aria-hidden>
              <Icon.spark size={12} />
            </div>
            <span className="pd-typing">
              <i />
              <i />
              <i />
            </span>
          </div>
        )}
        {status === "error" && (
          <ErrorBubble
            detail={error?.detail ?? "Something went wrong."}
            retryable={error?.retryable ?? true}
            onRetry={retry}
          />
        )}
      </div>

      <div className="pd-chat-composer">
        <div className="pd-chat-suggest">
          {SUGGESTIONS.map((s) => (
            <button key={s} className="pd-suggest-chip" onClick={() => send(s)} disabled={streaming}>
              {s}
            </button>
          ))}
        </div>
        <form
          className="pd-chat-input-row"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <textarea
            className="pd-chat-input"
            placeholder="Ask me about availability, prices, or just say 'book PS5 tonight'…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={1}
          />
          <button className="pd-send" disabled={!input.trim() || streaming} aria-label="Send">
            <Icon.send size={18} />
          </button>
        </form>
      </div>
    </div>
  );
}

function Bubble({
  role,
  content,
  tokens,
  tools,
  booking,
  streaming,
}: {
  role: "user" | "assistant";
  content: string;
  /** Per-delta tokens from the live stream; renders each as a fade-in span. */
  tokens?: string[];
  tools: ToolHint[];
  booking: number | null;
  streaming: boolean;
}) {
  if (role === "user") {
    return (
      <div className="pd-chat-row pd-chat-row--user">
        <div className="pd-bubble pd-bubble--user">{content}</div>
        <div className="pd-avatar pd-avatar--user" aria-hidden>
          You
        </div>
      </div>
    );
  }
  const showTokens = streaming && tokens && tokens.length > 0;
  return (
    <div className="pd-chat-row pd-chat-row--ai">
      <div className="pd-avatar pd-avatar--ai" aria-hidden>
        <Icon.spark size={14} />
      </div>
      <div className="pd-chat-col">
        {tools.length > 0 && (
          <div className="pd-tools">
            {tools.map((t) => (
              <span key={t.id} className={`pd-tool pd-tool--${t.status}`}>
                <span className="pd-tool-ico">
                  {t.status === "done" ? <Icon.check size={11} /> : <span className="pd-tool-spin" />}
                </span>
                <span className="pd-tool-name">{t.name}</span>
                {t.status === "running" && <span>…</span>}
              </span>
            ))}
          </div>
        )}
        {(showTokens || content) && (
          <div className="pd-bubble pd-bubble--ai">
            {showTokens
              ? tokens!.map((t, i) => (
                  <span key={i} className="pd-tok">
                    {t}
                  </span>
                ))
              : content}
          </div>
        )}
        {booking !== null && <BookingCard id={booking} />}
      </div>
    </div>
  );
}

function BookingCard({ id }: { id: number }) {
  return (
    <div className="pd-bcard">
      <div className="pd-bcard-head">
        <div className="pd-bcard-stamp">
          <Icon.check size={14} />
        </div>
        <div>
          <div className="pd-bcard-title">Booking confirmed</div>
          <div className="pd-bcard-id">#{id} · payment link sent by SMS</div>
        </div>
      </div>
      <div className="pd-bcard-actions">
        <button className="pd-btn pd-btn--ghost pd-btn--sm">Add to calendar</button>
        <button className="pd-btn pd-btn--ghost pd-btn--sm">View details</button>
      </div>
    </div>
  );
}

function ErrorBubble({
  detail,
  retryable,
  onRetry,
}: {
  detail: string;
  retryable: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="pd-chat-row pd-chat-row--ai">
      <div className="pd-avatar pd-avatar--ai" aria-hidden>
        <Icon.spark size={14} />
      </div>
      <div className="pd-chat-col">
        <div className="pd-error">
          <span className="pd-error-dot" />
          {detail}
        </div>
        {retryable && (
          <div>
            <button className="pd-btn pd-btn--ghost pd-btn--sm" onClick={onRetry}>
              Retry
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
