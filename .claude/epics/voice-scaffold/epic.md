---
name: voice-scaffold
status: backlog
created: 2026-05-24T01:00:22Z
updated: 2026-05-24T01:11:42Z
progress: 0%
prd: .claude/prds/voice-scaffold.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/148
---

# Epic: voice-scaffold

## Overview

One Twilio Voice webhook returning static bilingual TwiML, one Conversation row per inbound call (linked to a Customer if the caller's phone matches), one implementation plan document for the next agent. No STT, no TTS, no real agent turn — but a working phone path that proves the channel plumbing and unblocks the next-iteration design.

## Architecture Decisions

- **Static TwiML, not silent placeholder.** A 503 or a hung call would be a worse user experience than honest "voice coming soon, please text" guidance. The static greeting is bilingual (English + Mandarin) matching the agent's existing locale support.
- **Conversation row on call-answer, not call-ring.** Twilio fires the webhook on answer; ring events don't carry enough metadata to be useful. Missed-call attempts arrive via the separate `CallStatus=no-answer` callback — also captured.
- **Caller-identity link via `normalize_phone`.** Same helper that retention and the SMS adapter use. Anonymous callers (no Customer match) get a Conversation with `customer=None`.
- **Shared signature helper.** Voice reuses the same `_verify_twilio_signature` helper that `whatsapp` slice extracts (if both ship in the same v5, whichever lands first creates the helper). Both slices are written assuming the helper exists; whichever ships second imports it.
- **Implementation plan doc, not just code comments.** The next agent (or human) picking up real STT/TTS needs vendor evaluation, latency budget, and a partial-transcript-streaming design — too much for inline comments and too durable for a PR description.

## Technical Approach

### Frontend Components
- No new pages. The `/admin?channel=phone` filter chip already exists from v3 multi-channel; this slice just gives it data to filter.

### Backend Services
- `backend/api/webhooks_twilio.py` — extend with `twilio_voice_webhook(request)` view.
  - Verifies signature using the shared `_verify_twilio_signature` helper (extracted by `whatsapp` slice, or extracted by this slice if `whatsapp` hasn't landed).
  - Parses Twilio's POST body for `From` (caller's number) and `CallStatus`.
  - Looks up `Customer` by `normalize_phone(From)`; links if found.
  - Creates `Conversation(channel='phone', customer=..., customer_identifier=normalized_phone, status='completed')`.
  - Returns TwiML with bilingual `<Say>` greeting.
  - On missing `TWILIO_AUTH_TOKEN`: 503 with `{"error":"not_configured"}` body.
- `backend/api/urls.py` — register `POST /api/webhooks/twilio/voice/`.
- `backend/api/webhooks_twilio.py` — extend with a `twilio_voice_status_callback(request)` view for `CallStatus=no-answer` / `busy` / `failed` events; logs an attempted-but-missed `Conversation` row.

### Infrastructure
- No new pip deps (Twilio SDK + Django stdlib).
- No new env vars.
- `docs/voice-implementation-plan.md` (new) — sibling to the existing `docs/voice-ai-readiness.md`. Vendor recommendation, latency budget, cost ceiling, partial-transcript wiring, fallback, "what to build first."

## Implementation Strategy

Signature helper coordination first (read whether `whatsapp` slice has extracted it; if not, do it here). Then the webhook + tests. Then the status-callback view + tests. Then the implementation-plan doc — written last so the agent can reference the actual code it just wrote.

## Task Breakdown Preview

- 001 — Signature helper coordination: import from `twilio_signature.py` if it exists; otherwise extract it from the existing SMS adapter (idempotent with the `whatsapp` slice doing the same)
- 002 — `twilio_voice_webhook` view + bilingual TwiML + Conversation creation + Customer lookup + tests
- 003 — `twilio_voice_status_callback` view + missed-call Conversation row + tests
- 004 — `docs/voice-implementation-plan.md` — vendor + latency + cost + partial-transcript design + "what to build first"

## Dependencies

- Hard: `multi-channel` (in main) — Twilio env vars, `Conversation.channel='phone'` enum value.
- Hard: `retention` (in main) — `Customer`, `normalize_phone`.
- Soft: `whatsapp` (parallel v5) — if it ships first, the shared signature helper already exists; if voice ships first, this slice extracts it and `whatsapp` consumes it. Mirrors v3 retention↔multi-channel coordination.

## Success Criteria (Technical)

- With a real Twilio number pointed at the staging deploy, dialing the number plays the bilingual greeting and produces a `Conversation` row with `channel='phone'` visible in `/admin?channel=phone` within one minute.
- A missed call (no-answer) creates a `Conversation` row too.
- Without Twilio configured (no `TWILIO_AUTH_TOKEN`), the webhook returns 503 cleanly and the test suite passes.
- The implementation-plan doc covers all six required sections (sequence diagram, vendor stack, latency budget, cost ceiling, partial-transcript wiring, fallback, "what to build first") with no `TODO` placeholders.
- ≥4 new tests cover: signed-payload happy path, tampered signature (403), missing `TWILIO_AUTH_TOKEN` (503), missed-call status callback.

## Estimated Effort

- ~0.5 day total wall-time as a single agent. Sequential: 001 → 002 → 003 → 004.

## Tasks Created
- [ ] #149 - Signature helper coordination (extract or import the shared verifier) (parallel: false)
- [ ] #150 - twilio_voice_webhook view + bilingual TwiML + Conversation creation (parallel: false, depends on 001)
- [ ] #151 - twilio_voice_status_callback view + missed-call Conversation row (parallel: false, depends on 002)
- [ ] #152 - docs/voice-implementation-plan.md with full design coverage (parallel: false, depends on 002)

Total tasks: 4
Parallel tasks: 0
Sequential tasks: 4
