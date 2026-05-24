# Voice implementation plan

> The next layer down from [`docs/voice-ai-readiness.md`](voice-ai-readiness.md).
> That earlier doc establishes the channel-adapter seam and architectural
> framing; this one is concrete enough to start coding from.
>
> Current entry point (already in main as of v5):
> - [`twilio_voice_webhook`](../backend/api/webhooks_twilio.py) at
>   `POST /api/webhooks/twilio/voice/` — static bilingual `<Say>` greeting +
>   `Conversation(channel='phone', status='completed')` row.
> - [`twilio_voice_status_callback`](../backend/api/webhooks_twilio.py) at
>   `POST /api/webhooks/twilio/voice/status/` — missed-call rows with
>   `status='abandoned'`.
> - Shared signature verifier:
>   [`backend/agent/channels/twilio_signature.py`](../backend/agent/channels/twilio_signature.py).

## Overview

Take the v5 scaffold from "the call connects and we log it" to a full
STT → agent-loop → TTS round-trip over Twilio Voice, so a customer dialing
the store can ask the AI front desk for availability, place a booking, or
get routed to a human — all inside the same `AgentLoop` that already serves
web chat and SMS. The agent loop, booking tools, and RAG retriever stay
unchanged; voice is purely additive at the channel-adapter seam.

## Vendor stack recommendation

**Recommended: Twilio Media Streams + Deepgram Streaming STT + ElevenLabs Turbo v2 TTS.**

| Layer | Choice | Why |
|---|---|---|
| PSTN + WebSocket bridge | **Twilio Voice + `<Stream>`** | The Twilio account + number + signature plumbing already exists from SMS / WhatsApp; reusing it is one less integration. `<Start><Stream>` sends raw μ-law audio over WebSockets at ~20 ms frames. |
| Speech-to-text | **Deepgram Nova-3 Streaming** | Sub-200 ms first-partial latency, native WebSocket streaming, emits interim + final transcripts (essential for barge-in), strong on accented English and code-switched EN ↔ 中文. |
| Text-to-speech | **ElevenLabs Turbo v2** | ~250 ms first-audio latency, both EN + 中文 voices, streaming WebSocket API matches Twilio's frame rate. |
| Endpointing | **Server-side VAD (Silero)** | Decides when the caller stops speaking. Cheaper than running Deepgram-only endpointing and tuneable per store. |

**Alternative stack: Twilio + AssemblyAI Realtime STT + Azure Neural TTS.**
AssemblyAI's accuracy edges Deepgram on broadcast-quality audio but its
streaming latency is ~100 ms worse; Azure Neural is rock-solid and slightly
cheaper than ElevenLabs but lacks the same voice-cloning headroom. Pick this
stack if cost matters more than perceived "human-ness."

## Sequence

```mermaid
sequenceDiagram
    autonumber
    participant C as Caller
    participant T as Twilio Voice
    participant W as VoiceWebhook<br/>(Django + Channels)
    participant STT as Deepgram WS
    participant L as AgentLoop
    participant TTS as ElevenLabs WS
    participant DB as Postgres

    C->>T: Dial PlayDesk number
    T->>W: HTTP POST /api/webhooks/twilio/voice/
    W-->>T: TwiML &lt;Start&gt;&lt;Stream url=wss://.../voice/stream/&gt;
    T-)W: WS frames (μ-law 8kHz, 20ms)
    par STT pipeline
        W-)STT: forward audio frames
        STT-)W: partial transcripts (every ~100ms)
        Note over W: ① barge-in check:<br/>partial during TTS<br/>→ cancel TTS stream
        STT-)W: final transcript (on VAD silence)
    end
    W->>L: AgentLoop.run(user_content=final)
    L->>DB: tool calls (check_availability, create_booking)
    L-->>W: streamed reply tokens
    Note over W: ② start TTS as soon as<br/>first sentence is ready
    W-)TTS: synthesize(reply_chunk)
    TTS-)W: PCM audio chunks
    W-)T: WS audio frames back to caller
    T->>C: Plays response
    Note over W,DB: write Message rows<br/>(user transcript + assistant reply)
```

Two seams to watch: **①** is barge-in — any partial transcript that arrives
while TTS is mid-playback must cancel the TTS WebSocket. **②** is reply
streaming — start synthesising the first sentence of the agent's reply
before the loop finishes its full token stream; this is where ~400 ms of
felt latency lives.

## Per-step latency budget

Target conversational round-trip ≤ **1.5 s** from when the caller stops
speaking to when they hear the first syllable of the reply. Past that,
callers start interrupting themselves.

| Step | Target p95 | Notes |
|---|---|---|
| Twilio → our WS (network) | 50 ms | Twilio's edge POPs are co-located in major US regions; keep the app close. |
| STT first-partial | 150 ms | Streaming — we don't wait for the whole utterance. |
| STT endpointing (silence → final) | 250 ms | VAD-tunable. Tighter = more interruptions, looser = laggier. |
| Agent first-token (no tool call) | 600 ms | Claude Haiku 4.5 default for voice. Opus / Sonnet are too slow. |
| TTS first-audio | 300 ms | ElevenLabs Turbo v2 streams within ~250 ms; pad for jitter. |
| Network back to caller | 50 ms | Symmetric with inbound. |
| **First-audio round-trip** | **≈ 1400 ms** | Within budget. One tool call adds ~500 ms (≈1900 ms — borderline). |

If the agent needs more than one tool call, fire a 250 ms filler
("Let me check that for you...") via TTS before the second tool returns
so the line never goes silent for more than 800 ms.

## Per-call cost ceiling

Conservative estimate per minute, US-region streaming:

| Item | $/min |
|---|---|
| Twilio Voice inbound | ~$0.0085 |
| Twilio Media Streams (`<Stream>`) | ~$0.004 |
| Deepgram Nova-3 streaming STT | ~$0.0077 |
| ElevenLabs Turbo v2 (≈half the minute speaking) | ~$0.045 |
| Claude Haiku tokens (≈2k in / 1k out per turn × 4 turns) | ~$0.006 |
| **Total** | **≈ $0.07 / minute** |

A 3-minute booking call costs roughly $0.21. A 10-minute discovery /
complaint call costs ~$0.70. Implication for routing:

- **Auto-answer with voice agent**: short transactional queries — "what
  time do you close", "is the PS5 free Saturday 8pm", "I want to book
  the foosball table" — typically resolve in ≤2 turns.
- **Push to text (SMS / WhatsApp)**: anything that smells like a
  multi-step troubleshooting flow, payment dispute, or long preference
  conversation. The agent says "Let me text you so we can sort this
  out properly" and the existing SMS adapter takes over. Text is
  ~$0.005 per inbound message vs $0.07 per voice-minute.
- **Hard handoff to human**: out-of-hours, agent escalation
  (`unsafe_action` tool result), or three failed STT retries.

## Partial-transcript wiring

The current `AgentLoop.run` signature takes a complete user message
(`user_content: str`) and runs to completion. Voice needs to feed it
partial transcripts while keeping the loop's iteration cap intact.

The minimum change is to add a `streaming_input` mode that:

1. Accepts a generator of `(text, is_final: bool)` tuples instead of a
   single string.
2. Runs the loop only when `is_final=True` *and* the VAD has signalled
   end-of-utterance — partials are buffered to enable barge-in but never
   trigger an LLM call (otherwise we'd burn tokens on every interim
   transcript).
3. On barge-in (a new partial arrives during reply playback), cancels
   the in-flight TTS stream by closing its WebSocket, marks the
   half-spoken reply as truncated in the `Message` row, and starts a
   new loop iteration on the next final transcript.

File-level shape:

- `backend/agent/loop.py`: add `AgentLoop.run_streaming(transcripts, on_token, on_tool_result)` alongside the existing `run(...)`. Don't replace `run` — web chat and SMS keep using it unchanged.
- `backend/agent/channels/voice.py` (new): the `VoiceAdapter`. Implements `ChannelAdapter.normalize_inbound` to consume Deepgram's `{type: 'Results', ...}` JSON, yields `(transcript, is_final)` tuples, and routes them into `AgentLoop.run_streaming`.
- `backend/api/voice_ws.py` (new): a Django Channels or `channels-redis` WebSocket consumer that bridges Twilio's `<Stream>` frames ↔ Deepgram ↔ the voice adapter ↔ ElevenLabs ↔ Twilio.

The existing `Message` rows still capture user transcripts (`role='user'`,
content = final transcript) and assistant replies (`role='assistant'`,
content = full TTS text). Tool calls are recorded identically to web
chat. Staff reading `/admin/conversations/<id>/` see the voice call as
just another conversation transcript.

## Fallback behaviour

Voice is the most failure-prone channel. The ladder:

1. **STT WebSocket drops mid-call** — reconnect once with 100 ms
   backoff. On second failure, switch to a recorded "I'm having
   trouble hearing you, please hold" and dial the store's voicemail
   inbox; mark conversation `status='escalated'`.
2. **TTS WebSocket drops mid-reply** — finish playback via Twilio's
   built-in `<Say>` (Polly Joanna) on the same text. Caller hears a
   voice change but the reply completes.
3. **LLM unavailable** (same `llm_unavailable` code the SSE protocol
   emits today) — play "I need to transfer you to staff" + `<Dial>`
   to the configured handoff number; conversation `status='escalated'`.
4. **`unsafe_action` tool result** — same handoff path as #3.
5. **Caller drops mid-conversation (Twilio `CallStatus=completed` while
   loop still running)** — the existing v5 `twilio_voice_status_callback`
   already records the missed-call row. v4's outbound channel ([epic
   #97](https://github.com/Yuk1Neek0/PlayDesk/pull/97)) can send a
   templated SMS follow-up: "Sorry we got cut off — here's where we
   were: [last assistant reply]. Reply to continue."
6. **Quiet hours / no human available** — record a voicemail clip,
   transcribe it via Deepgram batch (not streaming, $0.0043/min), tag
   the `Conversation` `channel='phone'` so the morning shift sees it
   in `/admin?channel=phone`.

In every case the transcript is persisted in `Message` rows, identical
to web chat / SMS, so staff can read it back.

## What to build first

Three concrete next steps, in order, each sized as one PR-sized epic:

1. **WebSocket audio sink — connectivity proof.**
   Replace the static `<Say>` TwiML in
   `backend/api/webhooks_twilio.py::twilio_voice_webhook` with
   `<Start><Stream url="wss://.../api/voice/stream/">`. Stand up a
   Django Channels consumer at `backend/api/voice_ws.py` that accepts
   the connection, discards the audio frames, and logs the
   `connected` / `media` / `stop` events. Goal: prove Twilio's
   `<Stream>` reaches us and the WebSocket handshake works. *No
   STT / TTS / agent loop yet.*

2. **Deepgram pipe — transcripts to logfile.**
   Open a Deepgram streaming connection per call, pipe Twilio's μ-law
   frames into it, and append final transcripts to a per-call log.
   Add a `voice_stt_enabled` setting flag so we can roll back without
   redeploying. Goal: prove the STT vendor + audio format choices
   work end-to-end. Latency measured but not yet optimised.
   Files: `backend/agent/channels/voice.py` (new) implementing
   `normalize_inbound`; `backend/api/voice_ws.py` extended to call into it.

3. **Agent loop + static `<Say>` reply.**
   Wire `AgentLoop.run_streaming` (the new method described in
   "Partial-transcript wiring") to consume final transcripts and emit
   a reply. Speak the reply back via Twilio's built-in `<Say>` (not
   streaming TTS yet) so we can validate the conversational round-trip
   without taking on TTS provider risk. This is the "voicemail-style
   AI" milestone — the call works, just with ~3 s latency.
   Files: `backend/agent/loop.py` (add `run_streaming`);
   `backend/agent/channels/voice.py` (route finals into the loop);
   `backend/api/voice_ws.py` (send `<Say>` after each agent turn).

Steps 4–6 from [`docs/voice-ai-readiness.md`](voice-ai-readiness.md#what-to-build-first)
(streaming TTS, then barge-in, then voice cloning) are the long pole and
should land as their own slices — they're where most voice products live
or die.

## Cross-references

- Architectural framing: [`docs/voice-ai-readiness.md`](voice-ai-readiness.md)
- v5 scaffold entry point: [`backend/api/webhooks_twilio.py`](../backend/api/webhooks_twilio.py) (`twilio_voice_webhook` + `twilio_voice_status_callback`)
- URL registration: [`backend/api/urls.py`](../backend/api/urls.py)
- Shared signature verifier: [`backend/agent/channels/twilio_signature.py`](../backend/agent/channels/twilio_signature.py)
- Channel adapter base class: [`backend/agent/channels/base.py`](../backend/agent/channels/base.py)
- Existing SMS adapter (template for the voice one): [`backend/agent/channels/twilio_sms.py`](../backend/agent/channels/twilio_sms.py)
- Outbound channel (for dropped-call SMS recovery): [`backend/outbound/`](../backend/outbound/)
