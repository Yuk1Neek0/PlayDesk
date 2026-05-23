---
name: multi-channel
description: Make the agent backend channel-agnostic and ship an SMS adapter so PlayDesk's AI front desk matches COSReady's phone/text/web positioning.
status: backlog
created: 2026-05-23T04:27:55Z
---

# PRD: multi-channel

## Executive Summary

COSReady's headline AI feature is a 24/7 AI front desk that works across phone, text, and web. PlayDesk's agent only speaks one channel today: HTTP / SSE web chat. This epic refactors the agent backend behind a tiny adapter abstraction so the existing web chat stays unchanged, ships a working Twilio SMS adapter as proof, and lands a `docs/voice-ai-readiness.md` design doc so the voice story is articulated even though no STT / TTS code lands in v3.

This is the only piece salvaged from the earlier (now-superseded) v2 plan — kept because it aligns directly with COSReady's positioning rather than with inward-facing AI rigor.

## Problem Statement

The existing `POST /api/conversations/{id}/messages/` view bakes in HTTP-only assumptions: it reads a JSON body, runs the agent loop, and streams SSE back. There is no separation between *which channel the customer is using* and *what the agent does with the message*. Adding SMS, WhatsApp, or voice today requires copying agent-loop plumbing into a second view — and a second view inevitably drifts.

The bilingual story is similar: the agent already detects language, but customers reaching from SMS or voice should still get the same RAG-vs-SQL routing and the same booking-safety guarantees.

## User Stories

- **As a developer**, I can wire a new channel (Slack, WhatsApp, voice) by writing one `ChannelAdapter` subclass without editing the agent loop.
  - *Acceptance:* the existing web-chat path is rewritten as one such adapter, with no behaviour change visible to the existing chat UI.
- **As a reviewer**, I text the configured Twilio sandbox number from a real phone and get an AI reply within ~6 seconds. The conversation appears in `/admin` tagged `channel=sms`.
  - *Acceptance:* with `TWILIO_AUTH_TOKEN` set, the SMS round-trip works end to end against `ngrok` or staging; without the token, the webhook returns a clean `503 not_configured` and the test suite skips that case (no failure).
- **As staff**, I can filter `/admin` conversations by channel chip group.
  - *Acceptance:* clicking the `SMS` chip narrows the list to sms conversations in <300ms.
- **As an architect**, I can read `docs/voice-ai-readiness.md` and understand exactly how a phone call would land in the agent loop and what would be built first.

## Functional Requirements

1. **`Conversation.channel` field** — additive enum migration. Values: `web_chat | sms | whatsapp | phone | manual_staff`. Existing rows backfill to `web_chat`.
2. **`agent/channels/` package**:
   - `base.py`: `ChannelAdapter` ABC with `normalize_inbound(payload) -> NormalizedMessage` and `format_outbound(text, metadata) -> Response`. Pure Python, no Django imports.
   - `web_chat.py`: first concrete adapter; the existing `/api/conversations/{id}/messages/` view routes through it. SSE shape preserved character-for-character.
3. **Twilio SMS adapter** `agent/channels/twilio_sms.py`:
   - Verifies inbound signature using `TWILIO_AUTH_TOKEN`.
   - Normalises the inbound `Body` into a `NormalizedMessage` with `customer_identifier = E.164 phone`.
   - Routes through the same agent loop.
   - Returns TwiML containing the assistant reply.
4. **Twilio webhook** `POST /api/webhooks/twilio/sms/`:
   - Valid signed payload → 200 + TwiML.
   - Tampered signature → 403.
   - `TWILIO_AUTH_TOKEN` unset → 503 with `{"error":"not_configured"}` body.
5. **Admin channel filter**:
   - `GET /api/admin/conversations/?channel=sms` filters by channel.
   - Frontend chip group above the conversations list (`All | Web | SMS | WhatsApp | Phone | Staff`).
6. **`docs/voice-ai-readiness.md`** design doc:
   - Mermaid sequence diagram for phone → STT → agent → TTS → phone.
   - Provider options (Twilio Voice + Deepgram + ElevenLabs as one possible stack).
   - Latency budget with explicit per-step targets.
   - Fallback behaviour (graceful degradation, human handoff path).
   - "What to build first" section.

## Non-Functional Requirements

- WebChatAdapter rewrite is invisible to the frontend — the existing SSE protocol and the Playwright e2e suite must pass unchanged.
- Twilio signature verification is mandatory; no "skip in dev" toggle.
- `ChannelAdapter` base class is pure Python (no Django) so adapters stay portable.
- Voice doc is reviewer-ready — no `TODO`s, no placeholder prose.
- Twilio fallback (503) is silent in CI without secrets.

## Success Criteria

- All existing backend tests (157) pass after the adapter refactor.
- New web-chat test exercises `WebChatAdapter.normalize_inbound` and `format_outbound` directly without DRF.
- With Twilio test credentials in a staging env, a sent SMS produces an assistant reply within ~6s; without credentials, the webhook returns 503 cleanly and no test fails.
- The `/admin?channel=sms` filter narrows the list correctly against seed data containing mixed channels.
- The voice doc covers STT, agent, TTS, latency, fallback, and includes a Mermaid diagram.

## Constraints & Assumptions

- Twilio is the only SMS provider considered in v3 (test mode only). WhatsApp follows the same Twilio path in a future slice.
- Voice is design-only — no STT or TTS code lands in v3.
- Phone identity uses E.164. Cross-slice with `retention` if it ships: SMS conversations' `customer_identifier` reuses the same `normalize_phone()` helper so dedup against booking customers is automatic.

## Out of Scope

- Live voice pipeline (STT/TTS implementation).
- WhatsApp Business API.
- Outbound staff-to-customer messaging.
- Per-channel rate limiting.

## Dependencies

- Soft: `retention` — if its `normalize_phone()` is in main, the SMS adapter calls it; otherwise SMS adapter defines an internal helper with the same contract that `retention` adopts when it lands.
- No dependency on `one-qr`.
