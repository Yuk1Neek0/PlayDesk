"use client";

// AI front-desk chat — streaming replies, animated tool-call pills, inline
// booking card. Ported from the Claude Design handoff
// (playdeck/project/src/chat.jsx). Streaming and replies run on the
// prototype's canned mock; wiring to the real SSE stream (useChatStream from
// task #19) is the remaining work of task #21.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { Icon } from "@/components/pd-ui";

type ToolState = "running" | "done";

interface ToolCall {
  name: string;
  result?: string;
  duration?: number;
  state?: ToolState;
}

interface ChatBooking {
  id: number;
  resource: string;
  date: string;
  time: string;
  total: string;
}

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  tools: ToolCall[];
  streaming: boolean;
  booking: ChatBooking | null;
  suggestions: string[] | null;
}

interface Reply {
  tools: ToolCall[];
  text: string;
  booking?: ChatBooking;
  suggestions?: string[];
}

const SUGGESTIONS = [
  "Is the PS5 free Saturday 8 pm?",
  "Book the Switch for 4 people",
  "What board games do you have?",
  "How late are you open?",
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the transcript pinned to the latest message as it grows/streams.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && messages.length) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function send(text: string) {
    if (!text.trim() || streaming) return;
    const trimmed = text.trim();
    setMessages((m) => [
      ...m,
      { id: Date.now(), role: "user", content: trimmed, tools: [], streaming: false, booking: null, suggestions: null },
    ]);
    setInput("");
    setStreaming(true);
    setTimeout(() => respondTo(trimmed), 350);
  }

  function respondTo(userText: string) {
    const reply = pickReply(userText);
    const aid = Date.now() + 1;
    setMessages((m) => [
      ...m,
      { id: aid, role: "assistant", content: "", tools: [], streaming: true, booking: null, suggestions: null },
    ]);
    runStream(aid, reply);
  }

  // Walk the reply's tool calls one at a time (running → done), then stream text.
  function runStream(aid: number, reply: Reply) {
    let toolIdx = 0;
    function nextTool() {
      if (toolIdx >= reply.tools.length) {
        streamText(aid, reply);
        return;
      }
      const tool = reply.tools[toolIdx++];
      setMessages((m) =>
        m.map((x) => (x.id === aid ? { ...x, tools: [...x.tools, { ...tool, state: "running" }] } : x)),
      );
      setTimeout(() => {
        setMessages((m) =>
          m.map((x) =>
            x.id === aid
              ? {
                  ...x,
                  tools: x.tools.map((t, i) =>
                    i === x.tools.length - 1 ? { ...t, state: "done" } : t,
                  ),
                }
              : x,
          ),
        );
        setTimeout(nextTool, 250);
      }, tool.duration ?? 850);
    }
    nextTool();
  }

  // Reveal the reply text token by token.
  function streamText(aid: number, reply: Reply) {
    const tokens = reply.text.split(/(\s+)/);
    let i = 0;
    function tick() {
      i += 1;
      const partial = tokens.slice(0, i).join("");
      setMessages((m) => m.map((x) => (x.id === aid ? { ...x, content: partial } : x)));
      if (i < tokens.length) {
        setTimeout(tick, 22 + Math.random() * 18);
      } else {
        setMessages((m) =>
          m.map((x) =>
            x.id === aid
              ? {
                  ...x,
                  streaming: false,
                  booking: reply.booking ?? null,
                  suggestions: reply.suggestions ?? null,
                }
              : x,
          ),
        );
        setStreaming(false);
      }
    }
    tick();
  }

  const last = messages[messages.length - 1];

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
          <Bubble key={m.id} msg={m} onPickSlot={(s) => send(`Book that — ${s}`)} />
        ))}
        {last?.streaming && (
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

function Bubble({ msg, onPickSlot }: { msg: Message; onPickSlot: (s: string) => void }) {
  if (msg.role === "user") {
    return (
      <div className="pd-chat-row pd-chat-row--user">
        <div className="pd-bubble pd-bubble--user">{msg.content}</div>
        <div className="pd-avatar pd-avatar--user" aria-hidden>
          You
        </div>
      </div>
    );
  }
  return (
    <div className="pd-chat-row pd-chat-row--ai">
      <div className="pd-avatar pd-avatar--ai" aria-hidden>
        <Icon.spark size={14} />
      </div>
      <div className="pd-chat-col">
        {msg.tools.length > 0 && (
          <div className="pd-tools">
            {msg.tools.map((t, i) => (
              <span key={i} className={`pd-tool pd-tool--${t.state ?? "running"}`}>
                <span className="pd-tool-ico">
                  {t.state === "done" ? <Icon.check size={11} /> : <span className="pd-tool-spin" />}
                </span>
                <span className="pd-tool-name">{t.name}</span>
                {t.state === "running" && <span>…</span>}
                {t.state === "done" && t.result && <span className="pd-tool-res">{t.result}</span>}
              </span>
            ))}
          </div>
        )}
        {msg.content && (
          <div className="pd-bubble pd-bubble--ai">
            {msg.content}
            {msg.streaming && <span className="pd-caret" />}
          </div>
        )}
        {msg.suggestions && (
          <div className="pd-slot-suggest">
            {msg.suggestions.map((s) => (
              <button key={s} className="pd-chip pd-chip--suggest" onClick={() => onPickSlot(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
        {msg.booking && <BookingCard b={msg.booking} />}
      </div>
    </div>
  );
}

function BookingCard({ b }: { b: ChatBooking }) {
  return (
    <div className="pd-bcard">
      <div className="pd-bcard-head">
        <div className="pd-bcard-stamp">
          <Icon.check size={14} />
        </div>
        <div>
          <div className="pd-bcard-title">Booking confirmed</div>
          <div className="pd-bcard-id">#{b.id} · payment link sent by SMS</div>
        </div>
      </div>
      <div className="pd-bcard-grid">
        <div>
          <span className="pd-bcard-k">Resource</span>
          <span>{b.resource}</span>
        </div>
        <div>
          <span className="pd-bcard-k">Date</span>
          <span>{b.date}</span>
        </div>
        <div>
          <span className="pd-bcard-k">Time</span>
          <span className="pd-mono">{b.time}</span>
        </div>
        <div>
          <span className="pd-bcard-k">Total</span>
          <span className="pd-mono">¥ {b.total}</span>
        </div>
      </div>
      <div className="pd-bcard-actions">
        <button className="pd-btn pd-btn--ghost pd-btn--sm">Add to calendar</button>
        <button className="pd-btn pd-btn--ghost pd-btn--sm">View details</button>
      </div>
    </div>
  );
}

function initialMessages(): Message[] {
  return [
    {
      id: 1,
      role: "assistant",
      streaming: false,
      tools: [],
      booking: null,
      suggestions: null,
      content:
        "Hi — I'm the PlayDesk front desk. I can check availability, answer questions about consoles, rooms or board games, and finish a booking with you in a single chat. What are we doing tonight?",
    },
  ];
}

// Canned reply keyed off message keywords — stands in for the real agent loop.
function pickReply(q: string): Reply {
  const lower = q.toLowerCase();
  if (lower.includes("ps5") && /sat|saturday|8\s?pm|20:00/.test(lower)) {
    return {
      tools: [
        { name: "check_availability", result: "Sat 23 May · PS5 A & B", duration: 900 },
        { name: "lookup_price", result: "¥58/hr · 2 pads", duration: 600 },
      ],
      text:
        "Saturday 23 May at 20:00 — PS5 Station · A is free for up to 3 hours. ¥58/hr, two pads included. Should I lock in 2 hours under your number?",
      suggestions: ["20:00–22:00", "19:00–22:00", "20:00–23:00"],
    };
  }
  if (lower.includes("switch")) {
    return {
      tools: [
        { name: "check_availability", result: "Switch Station · today", duration: 850 },
        { name: "create_booking", result: "#4131 · pending payment", duration: 1200 },
      ],
      text:
        "Done — I've reserved the Switch Station for 4 players, tonight 19:00–21:00. Total ¥96. Pay within 10 minutes to lock it in; I'll text you the link.",
      booking: { id: 4131, resource: "Switch Station", date: "Thu 21 May 2026", time: "19:00 – 21:00", total: "96" },
    };
  }
  if (lower.includes("board") || lower.includes("catan") || lower.includes("game")) {
    return {
      tools: [{ name: "search_catalog", result: "180 titles · 6 free tables", duration: 750 }],
      text:
        "We've got 180 board games on the shelf — Catan, Wingspan, Azul, Spirit Island, Root… Tonight there are 6 tables open from 19:00 onward. ¥38/hr per table, up to 6 players. Want me to grab one?",
    };
  }
  if (lower.includes("open") || lower.includes("late") || lower.includes("hour")) {
    return {
      tools: [{ name: "lookup_policy", result: "business_hours.zh", duration: 500 }],
      text:
        "We're open 10:00 – 02:00, every day of the week. Last booking start is 23:00. Weekend nights fill up fast — happy to grab a slot now?",
    };
  }
  if (lower.includes("price") || lower.includes("cost") || lower.includes("how much") || lower.includes("¥")) {
    return {
      tools: [{ name: "lookup_price", result: "rate sheet", duration: 600 }],
      text:
        "PS5 / Switch consoles start at ¥48/hr. Private rooms ¥188–¥248/hr (fits 6–8). Board‑game tables ¥38/hr. Members get 10% off after 22:00 — want me to enroll you?",
    };
  }
  return {
    tools: [{ name: "understand_intent", result: "low confidence", duration: 700 }],
    text:
      "Got it — to help fastest, tell me what (PS5 / Switch / private room / board games), when, and how many people. Or pick a quick suggestion below.",
    suggestions: ["PS5 tonight 8 pm", "Private room Saturday", "Switch for 4 now"],
  };
}
