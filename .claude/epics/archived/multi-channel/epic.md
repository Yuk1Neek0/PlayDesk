---
name: multi-channel
status: completed
created: 2026-05-23T04:27:55Z
updated: 2026-05-23T14:10:41Z
progress: 100%
prd: .claude/prds/multi-channel.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/91
---

# Epic: multi-channel

## Overview

Refactor the agent backend behind a `ChannelAdapter` abstraction, rewrite the existing web-chat path as the first concrete adapter, ship a working Twilio SMS adapter + signed webhook, add a channel filter to admin, and land a voice-AI readiness design doc.

## Architecture Decisions

- **Base class is pure Python.** `agent/channels/base.py` has no Django imports — the abstraction stays portable for future runtimes.
- **WebChat rewrite is invisible to the frontend.** The SSE protocol shape and event names are preserved character-for-character; the existing Playwright suite is the regression guard.
- **Twilio signature verification is mandatory.** No "skip in dev" toggle. Tampered → 403, unset env → 503.
- **Voice stays design-only in v3.** Explicit scope cap; no STT/TTS code lands.
- **Phone normalisation** is the soft seam with `retention`. The SMS adapter calls the same `normalize_phone()` so SMS conversations dedup against booking customers automatically.

## Technical Approach

### Frontend Components
- One small filter chip group above the admin conversations list. No other UI changes — the chat page already speaks the web-chat protocol.

### Backend Services
- `backend/core/migrations/000X_conversation_channel.py` — additive `channel` column, default `web_chat`.
- `backend/agent/channels/base.py` — `ChannelAdapter` ABC + `NormalizedMessage` dataclass.
- `backend/agent/channels/web_chat.py` — first concrete adapter; the existing view delegates to it.
- `backend/agent/channels/twilio_sms.py` — second concrete adapter with signature verification.
- `backend/api/webhooks/twilio_sms.py` — DRF view.
- `backend/api/admin.py` — extend list view to accept `?channel=`.

### Infrastructure
- Two new optional env vars: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`.
- New design doc: `docs/voice-ai-readiness.md`.

## Implementation Strategy

Land the migration + base adapter + web-chat rewrite first (the gate is "existing chat tests still pass"). Twilio and the channel filter are then independent. The voice doc is pure content; it can go anywhere.

## Task Breakdown Preview

- 001 — Migration: Conversation.channel
- 002 — ChannelAdapter ABC + WebChatAdapter rewrite (the gated refactor)
- 003 — TwilioSmsAdapter + signed webhook + 503 fallback
- 004 — Channel filter: admin endpoint + frontend chip group
- 005 — docs/voice-ai-readiness.md

## Dependencies

- Hard: none.
- Soft: `retention` — SMS adapter uses `normalize_phone()` once both are in main. If `retention` lags, this slice defines a private helper with the same contract.

## Success Criteria (Technical)

- All 157 backend tests pass after the WebChat rewrite.
- New unit test exercises `WebChatAdapter.normalize_inbound` / `format_outbound` directly without DRF.
- Twilio webhook: 200 on valid signed payload, 403 on tampered signature, 503 `not_configured` when env unset — three tests.
- `/admin?channel=sms` narrows the conversation list correctly.
- Voice doc covers STT / agent / TTS, latency budget, fallback path, Mermaid diagram, "what to build first" section.

## Estimated Effort

- ~2.5 days for one developer.
- 001 → 002 sequential. 003 / 004 / 005 parallel after 002.

## Tasks Created
- [ ] 001.md - Migration: Conversation.channel (parallel: false)
- [ ] 002.md - ChannelAdapter ABC + WebChatAdapter rewrite (parallel: false)
- [ ] 003.md - TwilioSmsAdapter + signed webhook + 503 fallback (parallel: true)
- [ ] 004.md - Channel filter: admin endpoint + frontend chip group (parallel: true)
- [ ] 005.md - docs/voice-ai-readiness.md (parallel: true)

Total tasks: 5
Parallel tasks: 3
Sequential tasks: 2
Estimated total effort: 16 hours
