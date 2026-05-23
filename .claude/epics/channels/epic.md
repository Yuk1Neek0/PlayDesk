---
name: channels
status: backlog
created: 2026-05-23T03:55:28Z
updated: 2026-05-23T04:10:32Z
progress: 0%
prd: .claude/prds/channels.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/62
---

# Epic: channels

## Overview

Refactor the agent backend to be channel-agnostic. A small `agent/channels/` package defines a `ChannelAdapter` base class; the existing HTTP/SSE path becomes one concrete adapter (`web_chat`); a second concrete adapter (`twilio_sms`) plus webhook prove the abstraction works. Voice stays design-only — `docs/voice-ai-readiness.md`. Bilingual gets a polished demo path.

## Architecture Decisions

- **Adapter base class lives outside Django.** Pure Python in `agent/channels/base.py` so the abstraction stays portable.
- **`Conversation.channel` is enum, defaulting `web_chat`.** Existing seed data and tests stay compatible.
- **Twilio signature verification is mandatory.** The webhook returns 403 on any verification failure.
- **`TWILIO_AUTH_TOKEN` unset → endpoint returns 503 `not_configured`.** CI without secrets stays green.
- **Voice doc is design-only.** No STT / TTS code lands in v2 — explicit scope cap.

## Technical Approach

### Frontend Components
- One small filter chip group added to `/admin` conversations panel: `web_chat | sms | whatsapp | phone | manual_staff | all`.
- No other UI changes — the chat page already speaks the web_chat protocol.

### Backend Services
- `backend/core/migrations/000X_conversation_channel.py` — adds `channel` column with default `web_chat`.
- `backend/agent/channels/base.py` — `ChannelAdapter` ABC.
- `backend/agent/channels/web_chat.py` — first concrete adapter, replaces the inline view logic.
- `backend/agent/channels/twilio_sms.py` — second concrete adapter.
- `backend/api/webhooks/twilio_sms.py` — signature-verified POST endpoint.
- `backend/api/admin.py` — existing list endpoints accept `?channel=` filter.

### Infrastructure
- Two new env vars: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` (optional; absence is handled).
- Three new docs files: `docs/voice-ai-readiness.md`, `docs/demo-script.md` (extended bilingual section), `docs/architecture.md` updated with channel diagram (the architecture doc itself is owned by Stream E; this stream contributes the channel section).

## Implementation Strategy

The adapter refactor must keep the existing web-chat SSE shape unchanged — that's the gate. Twilio and the channel filter are then independent. The voice doc and bilingual polish are pure-content tasks done in parallel.

## Task Breakdown Preview

- 001 — Migration: add Conversation.channel
- 002 — ChannelAdapter base class + WebChatAdapter; rewrite the existing endpoint to route through it
- 003 — TwilioSmsAdapter + signature-verified POST /api/webhooks/twilio/sms/ + 503 fallback
- 004 — Channel filter on admin conversations endpoint + frontend chip group
- 005 — docs/voice-ai-readiness.md
- 006 — Bilingual demo polish: walkthrough in docs/demo-script.md + verification path

## Dependencies

- No hard cross-stream dependencies.
- Coordinates with Stream E on screenshot timing for bilingual flow.

## Success Criteria (Technical)

- Existing 154-test backend suite still passes after the WebChat adapter rewrite.
- New web-chat test exercises the path through `WebChatAdapter`.
- Twilio webhook returns 200 on a valid signed payload, 403 on a tampered signature, 503 when not configured.
- `/admin?channel=sms` narrows the conversation list correctly.
- Voice doc covers STT, agent loop, TTS, latency, fallback, Mermaid diagram.

## Estimated Effort

- ~3 days for one developer.
- 001 → 002 sequential; 003 / 004 parallel after 002. 005 / 006 fully parallel (no code deps).

## Tasks Created
- [ ] 001.md - Migration — add Conversation.channel (parallel: false)
- [ ] 002.md - ChannelAdapter base + WebChatAdapter rewrite (parallel: false)
- [ ] 003.md - TwilioSmsAdapter + signed webhook + 503 fallback (parallel: true)
- [ ] 004.md - Channel filter — admin endpoint + frontend chip group (parallel: true)
- [ ] 005.md - docs/voice-ai-readiness.md (parallel: true)
- [ ] 006.md - Bilingual demo polish — verification path + walkthrough (parallel: true)

Total tasks: 6
Parallel tasks: 4
Sequential tasks: 2
Estimated total effort: 20 hours
