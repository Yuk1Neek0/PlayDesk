---
name: channels
description: Make the agent backend channel-agnostic — channel field, ingestion adapter, optional Twilio SMS webhook, voice-AI readiness doc, and a polished bilingual demo path.
status: backlog
created: 2026-05-23T03:55:28Z
---

# PRD: channels

## Executive Summary

PlayDesk's agent loop currently assumes a single channel: a logged-in web user posting JSON over `/api/conversations/{id}/messages/`. This epic turns it channel-agnostic: a small adapter layer normalises inbound messages from web chat, SMS, WhatsApp, and (later) voice into the same `Conversation` + `Message` flow. It ships:

- a `Conversation.channel` field with a default of `web_chat`,
- an adapter package (`agent/channels/`) with `web_chat` as the first concrete adapter,
- an optional Twilio SMS webhook for live demonstration when credentials are present,
- a `docs/voice-ai-readiness.md` design document (no implementation),
- a polished bilingual demo path showing both EN and 中文 customer flows.

The Twilio webhook and the voice doc together let the interview claim "channel-ready architecture" with one working alt-channel as proof.

## Problem Statement

COSReady markets itself as a phone / SMS / web AI front-desk. PlayDesk currently demonstrates only web chat, and the backend bakes in HTTP-only assumptions. Without a clean abstraction the multi-channel claim is hand-waving. The bilingual story is similar — bilingual retrieval already exists, but no single demo path strings it together end-to-end with screenshots.

## User Stories

- **As a developer**, I can wire a new channel (Slack, SMS, WhatsApp) by writing one `BaseChannelAdapter` subclass without touching the agent loop.
  - *Acceptance:* the existing web-chat path is rewritten as one such adapter; no behaviour change.
- **As a reviewer**, I can text a Twilio sandbox number and get an SMS reply that went through the same agent loop, with the conversation visible in `/admin` tagged `channel=sms`.
  - *Acceptance:* with Twilio test credentials configured, the SMS round-trip works locally via `ngrok` or staging; without credentials, the endpoint exists and returns a clear "not configured" response (no test failure).
- **As staff**, I can filter `/admin` conversations by channel.
  - *Acceptance:* a channel chip group in the conversations panel filters in <300ms.
- **As a Chinese-speaking customer**, my Chinese question gets a Chinese reply and the same tool calls are made.
  - *Acceptance:* the demo path in `docs/demo-script.md` walks through one EN conversation and one 中文 conversation and both result in a successful booking with `lang` correctly threaded.
- **As an architect**, I can read `docs/voice-ai-readiness.md` and understand exactly how a phone call would land in the agent loop.

## Functional Requirements

1. **`Conversation.channel` field** — enum `web_chat | sms | whatsapp | phone | manual_staff`, default `web_chat`. Migration is additive.
2. **`agent/channels/` package** — `base.py` defines `ChannelAdapter` with `normalize_inbound(payload) -> NormalizedMessage` and `format_outbound(text, metadata) -> Response`. `web_chat.py` is the first concrete adapter; the existing `POST /api/conversations/{id}/messages/` view routes through it.
3. **Twilio SMS adapter** — `agent/channels/twilio_sms.py` plus `POST /api/webhooks/twilio/sms/` endpoint. Verifies the Twilio signature, normalises inbound message, runs the agent loop, returns the reply via Twilio's response shape. No-op cleanly when `TWILIO_AUTH_TOKEN` is unset.
4. **Admin channel filter** — chip group above the conversations list filters by channel. Defaults to "All".
5. **Bilingual demo path** — `docs/demo-script.md` includes both EN and 中文 walkthroughs with screenshots placeholders; the existing language-detection path is verified end-to-end against both.
6. **Voice-AI readiness doc** — `docs/voice-ai-readiness.md` covering: STT → agent → TTS architecture, provider choices (Twilio Voice, Deepgram, ElevenLabs), latency budget, fallback / handoff behaviour, an explicit "what to build first" section, and a Mermaid diagram.

## Non-Functional Requirements

- Web-chat adapter rewrite must keep the existing SSE protocol unchanged — no contract drift.
- Twilio signature verification is non-negotiable (security boundary).
- Adapter base class is pure Python, no Django imports — adapters can be reused outside DRF if needed.
- Voice doc is reviewer-ready (no `TODO`s).

## Success Criteria

- The existing 154-test backend suite still passes after the adapter refactor.
- A new web-chat smoke test exercises the path through `WebChatAdapter` rather than the previous direct path.
- With Twilio test credentials, a sent SMS produces an assistant reply within ~6s; without them, the endpoint returns `503 not_configured` and the test suite skips that case.
- `/admin` channel filter narrows the conversation list correctly with seed data of mixed channels.
- The bilingual demo script can be executed top-to-bottom by a reviewer; both languages reach a confirmed booking.

## Constraints & Assumptions

- Twilio is the only SMS provider considered (test mode only). WhatsApp follows the same Twilio path in v2.1.
- Voice is design-only in v2. No STT/TTS code lands.
- The bilingual polish is screenshots + script + verification — no model-side changes.

## Out of Scope

- Live voice pipeline (STT/TTS wiring).
- WhatsApp Business API certification.
- Outbound SMS from staff to customer (covered by Stream B's future v2.1 work).
- Per-channel rate limiting.

## Dependencies

- No hard dependencies on other v2 streams.
- Bilingual polish is reinforced by Stream E's case-study screenshots — coordinate the screenshot timing.
