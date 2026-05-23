---
name: ai-traces
description: Turn the existing per-turn Message log into a readable AI trace dashboard so a reviewer can explain any single conversation end-to-end.
status: backlog
created: 2026-05-23T03:55:28Z
---

# PRD: ai-traces

## Executive Summary

PlayDesk already persists every assistant turn — user message, tool call, tool result, assistant reply — into the `Message` table, and the agent loop already streams `tool_call_start` / `tool_call_end` events. This epic surfaces that material as a readable admin view at `/admin/ai-traces` so any single conversation can be inspected end-to-end: what RAG chunks were retrieved, which tools were called with which arguments, how long each step took, which model and prompt version produced the answer, and what the final booking outcome was.

This is **not** another eval set. The existing eval suite tests *expected* behaviour against fixtures; the trace dashboard explains what *actually* happened in a real conversation. The two layers are complementary: evals tell us whether the system passed; traces tell us why.

## Problem Statement

In a production AI front-desk, debugging questions are conversation-shaped: "why did the assistant say that?", "did it use RAG or SQL?", "was the slowness retrieval, LLM, or DB?", "did a tool fail and silently fall back?". Today those answers require reading the `Message` table by hand and cross-referencing the agent log. There is no UI a reviewer can open during the demo to show what is happening.

This is also the load-bearing artifact for several Stream B / C downstream stories — handoff reasons, prompt-version A/B comparisons, and cost-per-conversation reporting all read from the same per-step trace metadata.

## User Stories

- **As a reviewer demoing PlayDesk**, I can open `/admin/ai-traces`, pick a conversation, and walk a hiring manager through the assistant's reasoning step by step.
  - *Acceptance:* the page loads in <500ms for a 20-message conversation; every assistant turn is shown with its tool calls, retrieved RAG chunks, latency, and model.
- **As a developer**, I can see which `prompt_version` and `model_name` produced a given assistant turn so I can correlate behaviour with config.
  - *Acceptance:* every assistant turn shows both fields; missing values render as `unknown` rather than crashing.
- **As staff**, I can see when a tool returned an error and how the agent recovered.
  - *Acceptance:* the trace marks failed tool calls red and shows the error payload inline.

## Functional Requirements

1. **Trace metadata capture** — extend `core.Message` with `latency_ms: int`, `tokens_in: int`, `tokens_out: int`, `model_name: str`, `prompt_version: str`, and `retrieval_chunk_ids: JSONB[]`. All fields nullable so historical data renders cleanly. Populated by the agent loop on every assistant turn and tool result.
2. **Trace read API** — `GET /api/admin/conversations/{id}/trace/` returns the conversation's ordered turns with all the new fields plus the existing `content` / `tool_call_data`. Permission-gated to staff.
3. **Trace list page** — `/admin/ai-traces` lists conversations newest-first, with columns: id, customer identifier, message count, last activity, total latency, total cost estimate, final booking outcome.
4. **Trace detail page** — `/admin/ai-traces/[id]` renders the turn-by-turn view: user / assistant bubbles with tool-call chips, retrieved chunks shown collapsibly under the assistant turn that used them, per-step latency strip, totals at the top.
5. **Cost estimate** — a small helper converts `(model_name, tokens_in, tokens_out)` into an estimated dollar cost using a static `MODEL_PRICING` map; surfaced on every turn and summed for the conversation.

## Non-Functional Requirements

- Read-only — no agent behaviour changes; capture is additive.
- One additive migration; no destructive schema changes.
- Trace endpoint must paginate cleanly when a conversation exceeds 200 messages (cap at 200 with a "load more" tail).
- `prefers-reduced-motion` honoured — chunk collapse is an opacity-fade, not a translate.

## Success Criteria

- A reviewer can inspect one AI conversation end-to-end without leaving `/admin`.
- The dashboard clearly shows whether the assistant used RAG or SQL tools per turn.
- Tool failures and fallback turns are visually distinct.
- Latency and estimated cost are visible per turn and per conversation.
- The new fields are emitted by every fresh assistant turn produced by the agent loop.

## Constraints & Assumptions

- Builds on the existing `Message` model and `AgentLoop._build_system_prompt` plumbing.
- The model-pricing table is hard-coded (no live billing API) — explicit in the cost label.
- Existing admin auth-gate at `/admin` covers this route too; no new role logic.

## Out of Scope

- Live tailing of an in-flight conversation (would require WebSocket; v2.1 candidate).
- Cost attribution to customers or per-store billing.
- Replay / re-run of historical conversations against a new prompt.

## Dependencies

- No dependencies on other v2 streams. Lands first / fastest.
- Stream B (`operations`) reads `prompt_version` from this stream's schema once both are in main.
- Stream C (`quality-metrics`) reads `model_name`, `tokens_*`, `latency_ms` for its aggregate reports.
