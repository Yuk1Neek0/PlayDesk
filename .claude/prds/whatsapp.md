---
name: whatsapp
description: Twilio WhatsApp adapter on both inbound and outbound channels — closes the "SMS / WhatsApp messaging" item on the COSReady surface using the v3 / v4 adapter shapes already in main.
status: backlog
created: 2026-05-24T01:00:22Z
---

# PRD: whatsapp

## Executive Summary

The v3 multi-channel slice (`backend/agent/channels/twilio_sms.py`) and the v4 outbound slice (`backend/agent/channels/twilio_sms_outbound.py`) already established the inbound and outbound adapter shapes the project needs. Adding WhatsApp is a near-mirror of the SMS adapters: same Twilio SDK, same E.164 identifier, same channel-agnostic `NormalizedMessage` / `OutboundSendResult` contracts. `Conversation.channel` already includes `'whatsapp'` as a choice (added in the v3 `0007_conversation_channel` migration) and the admin chip filter already lists it.

This epic ships the missing wiring: a `TwilioWhatsAppAdapter` for inbound, a `TwilioWhatsAppOutboundAdapter` for outbound, a webhook view for inbound, registry entries on both sides, and the same `not_configured` graceful-degrade behaviour the SMS adapters already have.

## Problem Statement

COSReady advertises "SMS / WhatsApp messaging" as one product surface. PlayDesk handles SMS end-to-end but cannot send or receive WhatsApp messages. The infrastructure to add WhatsApp exists — adapters, channel enum, admin filter, env-var conventions — it just hasn't been instantiated for the WhatsApp channel.

WhatsApp matters specifically for the bilingual customer base the agent already supports: Chinese-speaking customers in Toronto reach businesses via WeChat (already a one-QR chip) and WhatsApp far more than SMS.

## User Stories

- **As a customer**, I can message the store's Twilio WhatsApp number from a real phone and get an AI-driven reply within ~6 seconds.
  - *Acceptance:* a sandbox WhatsApp message round-trips through the agent loop end-to-end; the conversation appears in `/admin` tagged `channel=whatsapp`.
- **As a customer**, after I book through the agent (any channel), I receive my booking_confirmation over WhatsApp if my identifier matches a WhatsApp number.
  - *Acceptance:* the existing v4 outbound signal enqueues an `OutboundMessage` with `channel='whatsapp'`; the cron sender routes it to the WhatsApp adapter, which posts back over Twilio's WhatsApp API.
- **As a developer**, the WhatsApp adapter shares zero code with the SMS adapter except the Twilio client setup — both follow the existing ABC contract.
- **As a CI maintainer**, when no `TWILIO_WHATSAPP_FROM` is configured the adapter cleanly returns `not_configured` (mirrors SMS) and the test suite passes without a real WhatsApp sandbox.

## Functional Requirements

1. **`TwilioWhatsAppAdapter`** in `backend/agent/channels/twilio_whatsapp.py`:
   - Verifies inbound signature using `TWILIO_AUTH_TOKEN` (reuses existing helper from `twilio_sms.py`).
   - Normalises Twilio's `whatsapp:+E.164` inbound `From` into a plain E.164 `customer_identifier` (strips the `whatsapp:` prefix).
   - Routes through the same agent loop as SMS.
   - Returns TwiML with the assistant reply.
2. **`TwilioWhatsAppOutboundAdapter`** in `backend/agent/channels/twilio_whatsapp_outbound.py`:
   - Uses `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` + a new `TWILIO_WHATSAPP_FROM` env var (Twilio requires a different `From` for WhatsApp than for SMS).
   - Prepends `whatsapp:` to both `From` and `To` per Twilio's API requirement.
   - Returns `OutboundSendResult(ok=False, reason="not_configured")` when `TWILIO_WHATSAPP_FROM` is missing.
3. **Webhook** `POST /api/webhooks/twilio/whatsapp/`:
   - Valid signed payload → 200 + TwiML.
   - Tampered signature → 403.
   - `TWILIO_AUTH_TOKEN` unset → 503 (mirrors SMS).
4. **Registry wiring** — both inbound and outbound channel registries gain a `'whatsapp'` entry pointing at the new adapter classes.
5. **Channel detection on outbound side** — `OutboundMessage.channel='whatsapp'` is opportunistic for v5: if a customer's most recent inbound conversation had `channel='whatsapp'`, future outbound messages to that customer default to WhatsApp. Otherwise default stays SMS. Implementation: lookup helper `pick_channel_for(customer) -> 'sms' | 'whatsapp'` consulted by the v4 outbound `enqueue_message`.
6. **Admin filter** — the existing chip group on `/admin` (`All | Web | SMS | WhatsApp | Phone | Staff`) already includes WhatsApp and works once Conversation rows with `channel='whatsapp'` exist.

## Non-Functional Requirements

- New file pair only — no edits to the existing SMS adapters.
- The signature-verification helper is extracted from `twilio_sms.py` into a shared module if needed (single source of truth across SMS and WhatsApp).
- Tests pass with no Twilio WhatsApp creds — `not_configured` paths leave queued rows alone and webhook returns 503 cleanly.
- One additive migration is NOT needed — the channel enum already includes `whatsapp`.

## Success Criteria

- With sandbox WhatsApp creds in staging, a sent WhatsApp produces an assistant reply within ~6s round-trip.
- Without creds, the entire test suite passes and no `OutboundMessage` ever transitions to `failed` because of WhatsApp.
- A customer who has previously messaged via WhatsApp gets their next outbound booking_confirmation over WhatsApp; one who has only used SMS still gets SMS.
- The `/admin?channel=whatsapp` chip narrows the conversation list correctly against seed data containing a mixed-channel conversation.

## Constraints & Assumptions

- Twilio is the only WhatsApp provider — no Meta direct API in v5.
- Sandbox-tier accounts only in v5; production WhatsApp Business approval is a separate ops concern.
- A customer's "preferred channel" is implicit (most-recent inbound channel), not explicitly configured. Explicit channel preference is out of scope.

## Out of Scope

- Meta WhatsApp Cloud API (direct).
- Customer-configurable channel preference UI.
- WhatsApp template messaging (the v5 sender uses free-form messages; Twilio sandbox accepts them inside the 24-hour customer-initiated session window).
- WhatsApp media (image / document) handling.

## Dependencies

- Hard: `multi-channel` (in main) — `ChannelAdapter` ABC + Twilio env vars + signature verification helper.
- Hard: `outbound` (in main) — `OutboundChannelAdapter` ABC + adapter registry + `enqueue_message`.
- Hard: `retention` (in main) — `Customer` for the channel-preference lookup.
- No dependencies on the other v5 slices.
