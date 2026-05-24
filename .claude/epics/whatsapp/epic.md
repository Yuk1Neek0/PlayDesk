---
name: whatsapp
status: backlog
created: 2026-05-24T01:00:22Z
updated: 2026-05-24T01:11:42Z
progress: 0%
prd: .claude/prds/whatsapp.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/131
---

# Epic: whatsapp

## Overview

Two new adapter files (inbound + outbound), one new webhook route, two registry entries, one new env var, one new helper for channel-preference lookup. Zero migrations — `Conversation.channel` already has `'whatsapp'` from v3 and the admin chip filter already shows it.

## Architecture Decisions

- **Mirror the SMS adapters, do not abstract over them.** Twilio's WhatsApp API is similar to SMS but not identical (the `whatsapp:` prefix on `From`/`To`, a separate sender number env var, message-template constraints outside the 24-hour session window). A shared base class would obscure these differences for a 2-instance hierarchy. Two near-identical files are easier to read and diverge later.
- **Channel-preference is implicit, not stored.** A customer's preferred outbound channel is computed at enqueue time from their most recent inbound conversation's `channel`. Storing an explicit `Customer.preferred_channel` would need a UI to set it and a migration; the implicit lookup gives the right answer without either.
- **Signature-verification helper extracted, not duplicated.** The existing `twilio_sms.py` has its own signature check; this slice extracts a shared `_verify_twilio_signature(request, auth_token) -> bool` helper used by SMS, WhatsApp, and (in `voice-scaffold`) Voice.
- **`not_configured` graceful-degrade is non-negotiable.** Same posture as SMS and outbound — missing creds return a clear "not configured" reason, never raise. CI without WhatsApp creds passes green.

## Technical Approach

### Frontend Components
- No new pages. The admin chip filter for `channel=whatsapp` already exists from v3 — once `Conversation` rows with `channel='whatsapp'` exist, the chip starts narrowing the list correctly.

### Backend Services
- `backend/agent/channels/twilio_whatsapp.py` — `TwilioWhatsAppAdapter(ChannelAdapter)`. Strips `whatsapp:` prefix from inbound `From`, normalises to E.164.
- `backend/agent/channels/twilio_whatsapp_outbound.py` — `TwilioWhatsAppOutboundAdapter(OutboundChannelAdapter)`. Prepends `whatsapp:` to `From`/`To` in the Twilio API call.
- `backend/agent/channels/twilio_signature.py` (new shared helper) — extract the signature-verification logic currently inline in `twilio_sms.py`. Both SMS and WhatsApp adapters use it.
- `backend/agent/channels/registry.py` — add `'whatsapp'` entries for both inbound and outbound registries.
- `backend/api/webhooks_twilio.py` — extend with `twilio_whatsapp_webhook(request)` view; same signature-check + adapter-call shape as the existing SMS webhook.
- `backend/outbound/api.py::enqueue_message` — extend to call a new `pick_channel_for(customer)` helper that resolves the channel: if the customer's most recent `Conversation` has `channel='whatsapp'`, default to WhatsApp; else default to SMS.
- `backend/outbound/channel_pref.py` (new) — `pick_channel_for(customer) -> 'sms' | 'whatsapp'`. One query, indexed on `Conversation.customer + created_at DESC LIMIT 1`.

### Infrastructure
- New env var `TWILIO_WHATSAPP_FROM` (e.g. `whatsapp:+14155238886` for the Twilio sandbox). Documented in `docs/outbound-cron.md` and `.env.example` (if present, otherwise just the cron doc).
- No new pip deps (Twilio SDK already in main).

## Implementation Strategy

Adapters first (independent), then webhook + registry (depends on adapters), then channel-preference helper (depends on outbound's `enqueue_message`). The adapters can be written and tested before the webhook + helper land.

## Task Breakdown Preview

- 001 — Extract `_verify_twilio_signature` to shared helper; refactor SMS adapter to use it (no behaviour change)
- 002 — `TwilioWhatsAppAdapter` (inbound) + tests
- 003 — `TwilioWhatsAppOutboundAdapter` + registry entry + tests
- 004 — `twilio_whatsapp_webhook` view + URL conf + signature/503 tests
- 005 — `pick_channel_for()` helper + integration into `enqueue_message` + tests for the "most-recent-conversation wins" rule

## Dependencies

- Hard: `multi-channel` (in main) — `ChannelAdapter`, Twilio env vars, existing signature-check pattern.
- Hard: `outbound` (in main) — `OutboundChannelAdapter`, adapter registry, `enqueue_message`.
- Hard: `retention` (in main) — `Customer` for the channel-preference lookup.
- Soft: none.

## Success Criteria (Technical)

- All existing 397-test backend suite passes after the signature-helper refactor (#001) — proven by running it before any other change.
- With sandbox WhatsApp creds in staging, a sent WhatsApp produces an assistant reply within ~6s; without creds, the webhook returns 503 cleanly and no test fails.
- A customer who has previously messaged via WhatsApp gets their next outbound `booking_confirmation` over WhatsApp; one who hasn't still gets SMS. Covered by a `pick_channel_for` unit test.
- The `/admin?channel=whatsapp` chip narrows the list against a seeded WhatsApp conversation.
- ≥8 new tests cover: inbound adapter normalisation, signature-verification helper round-trip, outbound adapter not_configured path, outbound adapter Twilio success path, webhook signed/tampered/503, `pick_channel_for` defaults.

## Estimated Effort

- ~0.5 day total wall-time as a single agent. Sequential: 001 → 002 → 003 → 004 → 005.

## Tasks Created
- [ ] #132 - Extract _verify_twilio_signature to shared helper (parallel: false)
- [ ] #133 - TwilioWhatsAppAdapter (inbound) + tests (parallel: false, depends on 001)
- [ ] #134 - TwilioWhatsAppOutboundAdapter + registry + tests (parallel: false, depends on 001)
- [ ] #135 - twilio_whatsapp_webhook view + URL conf + tests (parallel: false, depends on 002)
- [ ] #136 - pick_channel_for() helper + enqueue_message integration (parallel: false, depends on 003)

Total tasks: 5
Parallel tasks: 0 (each builds on the previous; one agent works it sequentially)
Sequential tasks: 5
