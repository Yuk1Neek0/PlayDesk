---
name: voice-scaffold
description: Twilio Voice webhook scaffold + deeper design doc — proves the voice surface is plumbing-ready without committing to STT / TTS spend in v5.
status: backlog
created: 2026-05-24T01:00:22Z
---

# PRD: voice-scaffold

## Executive Summary

The v3 multi-channel slice shipped `docs/voice-ai-readiness.md` as a design document but no executable voice path. COSReady's headline AI feature is a 24/7 AI front desk "across phone, text, and web" — phone has been a known gap. The blocker isn't architecture (the design doc names Twilio Voice + Deepgram + ElevenLabs as one reasonable stack); it's the operational cost of running STT and TTS for every call.

This epic ships the **scaffold**: a Twilio Voice webhook that responds to inbound calls with a TwiML message and records the call attempt as a `Conversation` with `channel='phone'`. No STT, no TTS, no real LLM turn — but a real Twilio number can point at PlayDesk and get a graceful, branded response, and the admin chip filter (`channel=phone`) starts showing real data instead of always-empty. The deeper implementation doc lands alongside so the next iteration has a one-page handoff.

## Problem Statement

Today, the `phone` channel is named in three places (`Conversation.channel` enum, the admin chip filter, the design doc) but no row ever has `channel='phone'`. A reviewer testing the "AI front desk across phone, text, and web" claim discovers there is no working phone path at all.

Going from this state to a fully working STT → agent → TTS round-trip is multi-week and per-call-cost — a real product decision, not a v5 ship-it call. But the gap between "no phone at all" and "phone scaffolded" is one day: a webhook, a TwiML response, a `Conversation` row, and a doc that the next agent can pick up.

## User Stories

- **As a customer**, when I dial the Twilio number my call connects, I hear a short message acknowledging me, and I'm offered the option to text instead (with the same number).
  - *Acceptance:* a test call to the configured Twilio number is answered within 2 rings; the audio message is intelligible; the call is logged as a `Conversation` with `channel='phone'`.
- **As staff**, every inbound voice call shows up in `/admin?channel=phone` with the caller's number, timestamp, and call status — even without a transcript.
  - *Acceptance:* the admin chip group's "Phone" tab is no longer always empty after this slice lands.
- **As an architect**, I can read `docs/voice-implementation-plan.md` and understand exactly what to build next: which STT / TTS vendors, what latency budget per step, where the partial-transcript stream plugs into the agent loop, and the cost ceiling per call.
- **As a CI maintainer**, the voice webhook works without any Twilio Voice account configured — it returns a graceful 503 / TwiML and no test fails.

## Functional Requirements

1. **Twilio Voice webhook** `POST /api/webhooks/twilio/voice/`:
   - Verifies inbound signature with `TWILIO_AUTH_TOKEN`.
   - Returns TwiML with a `<Say>` element delivering a short bilingual greeting: "You've reached PlayDesk. Voice is coming soon — please text us at this number for now. 中文您也可以發短信給我們。"
   - Records a `Conversation` row with `channel='phone'`, `customer_identifier=<caller's E.164 phone>`, `status='completed'`.
   - On missing `TWILIO_AUTH_TOKEN`: returns `503 not_configured` (mirrors SMS).
2. **Caller-identity link** — when the caller's phone matches a known `Customer` (via the existing `normalize_phone` helper), the conversation links to that customer FK; otherwise the conversation is anonymous (`customer=None`).
3. **`docs/voice-implementation-plan.md`** (new, distinct from the existing readiness doc):
   - Mermaid sequence diagram: caller → Twilio Voice → STT → agent loop → TTS → caller.
   - Recommended vendor stack with per-step latency budget (Twilio Media Streams + Deepgram streaming STT + ElevenLabs streaming TTS as one example).
   - Per-call cost ceiling (rough estimate: ~$0.05–$0.10 per minute) and the implication for which questions should auto-route to voice vs. push the caller to text.
   - Partial-transcript streaming: where Deepgram's WebSocket plugs into the agent loop; how interim transcripts vs. final transcripts are handled.
   - Fallback behaviour: human-handoff path, dropped-call recovery via outbound follow-up.
   - "What to build first" — three concrete next steps for the agent that picks this up.
4. **No STT / TTS code in v5** — explicitly out of scope. The webhook returns a static TwiML message.
5. **Admin filter parity** — `/admin?channel=phone` already filters correctly; just needs phone rows to exist (which #1 produces).

## Non-Functional Requirements

- The webhook adds no new pip deps in v5 (uses existing Twilio SDK + Django stdlib).
- The `<Say>` voice + language pick (`<Say language="en-US" voice="Polly.Joanna">` for English, then `<Say language="cmn-CN">` for the Chinese line) is documented in the TwiML body so the message is editable without code changes — but version-controlled there.
- Signature verification is mandatory; no "skip in dev" toggle (same posture as SMS).
- The webhook returns a `Conversation` row even on a missed call (Twilio's `CallStatus=no-answer` callback), so the admin filter shows attempted-but-missed calls too.

## Success Criteria

- With a real Twilio number pointed at the staging deploy, dialing the number plays the greeting message and produces a `Conversation` row visible in `/admin?channel=phone` within one minute.
- Without Twilio Voice configured (no `TWILIO_AUTH_TOKEN`), the test suite passes and the webhook returns 503 cleanly.
- The implementation plan doc covers STT, TTS, latency budget, fallback, cost, and the partial-transcript wiring — with no `TODO` placeholders.
- A future engineer (human or agent) can read the plan and start implementation without further design work.

## Constraints & Assumptions

- Twilio is the only voice provider considered in v5.
- The greeting message is bilingual but static — no dynamic personalisation per caller in this slice.
- No call recording is stored in v5 (Twilio's recording feature is off; only the conversation metadata persists).
- The Conversation row is created on call answer, not on call ring — matches the Twilio webhook event timing.

## Out of Scope

- Real STT (Deepgram, Whisper, AssemblyAI, etc.).
- Real TTS (ElevenLabs, Azure, Polly streaming, etc.).
- Two-way voice — the v5 scaffold is one-way (caller hears a message, conversation ends).
- IVR menus / digit-collection flows.
- Outbound voice (the store calling a customer back) — would be a follow-on slice.
- Call recording / transcript storage.

## Dependencies

- Hard: `multi-channel` (in main) — Twilio env vars, signature-verification helper, `Conversation.channel` enum (already includes `'phone'`).
- Hard: `retention` (in main) — `Customer` + `normalize_phone` for caller-identity linkage.
- No dependencies on other v5 slices.
