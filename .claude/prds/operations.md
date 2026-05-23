---
name: operations
description: Add human-in-the-loop handoff workflow plus prompt-config versioning so AI behaviour can be supervised, escalated, and released safely.
status: backlog
created: 2026-05-23T03:55:28Z
---

# PRD: operations

## Executive Summary

Two production-shaped capabilities, fused into one epic because both touch the agent loop and add new fields to `Conversation` / `Message`: (1) a **human handoff queue** at `/admin/handoff` for conversations the AI shouldn't fully handle, and (2) a **`PromptConfig` table** so the active system prompt + model + retrieval parameters can be swapped without a code change, and every assistant turn records which version produced it.

Bundling avoids two competing migrations on the same tables and lets one owner reason about agent-loop changes coherently.

## Problem Statement

A demo-grade AI front-desk silently keeps trying when it shouldn't — angry customers, repeated tool failures, refund requests, low-confidence policy answers all currently end with a generic "let me hand this over to a human teammate" message that is *not* actually routed to a human. Staff have no inbox.

Separately, the system prompt is a Python string literal. Iterating on prompt wording requires a code change, a deploy, and a loss of correlation between "which prompt produced which answer" — fatal for the quality-monitoring story in Stream C.

## User Stories

- **As staff**, I can open `/admin/handoff` and see exactly the conversations that need human attention, with the reason highlighted.
  - *Acceptance:* every conversation in the queue shows handoff reason, age, last message, and a "Take over" / "Mark resolved" pair of buttons.
- **As a customer**, when the AI decides it cannot help, the conversation transitions cleanly to a wait-state with a polite message and the AI stops attempting actions.
  - *Acceptance:* after handoff, the next user message does not trigger an agent loop run; staff sees it as a new inbound message in the queue.
- **As a developer**, I can switch the active prompt by toggling `PromptConfig.is_active` and the next conversation immediately uses the new system prompt.
  - *Acceptance:* no code change, no restart; the prompt-version field on the next `Message` row reflects the change.
- **As a reviewer**, I can compare two prompt versions later because every assistant turn carries `prompt_version` and `model_name`.

## Functional Requirements

1. **Conversation state migration** — add `Conversation.status` enum: `active | ai_resolved | needs_human | staff_takeover | closed`. Add `handoff_reason: text | null` and `handoff_at: datetime | null`. Default `active`.
2. **PromptConfig model** — `name`, `version`, `system_prompt: text`, `model_name`, `temperature: float`, `retrieval_top_k: int`, `is_active: bool`, `created_at`. Constraint: at most one row per `name` has `is_active=true`.
3. **Active-prompt resolver** — `AgentLoop._build_system_prompt` looks up the active `PromptConfig` once per turn (cached for the loop's lifetime); the resolved version is stamped onto every `Message` the loop writes.
4. **Handoff triggers** — fire when any of: (a) two consecutive tool calls fail, (b) the 6-iteration cap is reached, (c) user message contains explicit human-request keywords (`speak to`, `human`, `manager`, `refund`, `complaint`, plus the Chinese equivalents), (d) a tool returns a structured `unsafe_action` error. Each trigger sets `conversation.status = needs_human` and writes `handoff_reason`.
5. **`/admin/handoff` page** — staff-gated list of `needs_human | staff_takeover` conversations, newest first. Row shows: id, customer identifier, latest message preview, handoff reason, age, `[Take over]` / `[Mark resolved]` actions.
6. **Take-over action** — flips `status` to `staff_takeover`; the AI stops generating responses on this conversation (the agent loop early-returns when invoked on a non-`active` conversation).
7. **Mark-resolved action** — flips `status` to `closed`, prompts staff for a one-line resolution note (stored on the conversation row).
8. **Seed config** — fixture inserts `prompt_v1_basic` (the current literal) as the active default so existing tests keep working unchanged.

## Non-Functional Requirements

- Single combined migration for `Conversation` + `PromptConfig` so the schema lands atomically.
- Agent-loop change must be backwards-compatible: if no `PromptConfig` exists, fall back to the literal `SYSTEM_PROMPT` constant.
- Handoff triggers must not run inside the LLM client; they execute in the agent loop's outer harness so a runaway LLM cannot bypass them.
- `prefers-reduced-motion` honoured on the handoff queue.

## Success Criteria

- Two consecutive tool failures on a test conversation → `status` flips to `needs_human` and the row appears in `/admin/handoff` within one poll cycle.
- Staff `Take over` button blocks further AI replies; staff `Mark resolved` closes the conversation.
- Switching `PromptConfig.is_active` to a new version is reflected in the very next assistant turn's `prompt_version` field.
- The existing 154-test backend suite still passes (the fallback path preserves current behaviour).

## Constraints & Assumptions

- Reuses the existing `/admin` auth gate.
- The `unsafe_action` structured tool error is a new shape but additive on existing `BookingConflictError`-style returns.
- No staff-to-customer messaging UI is in scope — `Mark resolved` is a status flip; actual reply happens out-of-band for v2.

## Out of Scope

- Real-time staff reply channel back to the customer (the next epic).
- Per-store staff routing.
- Webhooks to external ticketing systems.
- Prompt A/B traffic-splitting — only one prompt is active at a time.

## Dependencies

- Reads `prompt_version` capture once Stream A's `ai-traces` lands. Soft dep: if A is not merged, this stream writes the field but nothing reads it yet.
- Stream C's quality report consumes `handoff_reason` + `prompt_version`. Soft dep: C handles missing fields gracefully.
