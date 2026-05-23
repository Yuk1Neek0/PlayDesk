---
name: operations
status: backlog
created: 2026-05-23T03:55:28Z
updated: 2026-05-23T04:10:12Z
progress: 0%
prd: .claude/prds/operations.md
github: https://github.com/Yuk1Neek0/PlayDesk/issues/50
---

# Epic: operations

## Overview

Fuse human-handoff and prompt-versioning into one epic because both add fields to `Conversation` / `Message` and both touch the agent loop. One combined migration; one set of agent-loop changes; two new admin surfaces.

## Architecture Decisions

- **One combined migration.** Adding `Conversation.status / handoff_reason / handoff_at` and the new `PromptConfig` table in a single revision keeps schema state simple.
- **Handoff triggers live in the agent-loop harness, not in tool implementations.** A misbehaving LLM cannot suppress them.
- **`PromptConfig` cache scope = one agent-loop invocation.** The active row is fetched once per turn, then re-fetched on the next turn — so switches take effect immediately without restart, but a single turn sees a stable config.
- **Backwards-compatible fallback.** If no `PromptConfig` row exists, the loop falls back to the literal `SYSTEM_PROMPT` constant — preserving the 154-test baseline.

## Technical Approach

### Frontend Components
- `frontend/src/app/admin/handoff/page.tsx` — staff-only handoff queue.
- `frontend/src/components/handoff-row.tsx` — single row with `Take over` / `Mark resolved` actions.
- A small modal for the resolution note when staff click `Mark resolved`.

### Backend Services
- `backend/core/migrations/000X_conversation_status_and_prompt_config.py` — combined migration.
- `backend/core/models.py` — `Conversation.status` choices, `PromptConfig` model, `is_active` partial unique index.
- `backend/agent/prompt_config.py` — `get_active_config(name='default')` + cache invalidation hook.
- `backend/agent/loop.py` — resolve active config at turn-start; detect handoff triggers; early-return on non-`active` conversation.
- `backend/api/admin_handoff.py` — list / take-over / mark-resolved endpoints.

### Infrastructure
- Seed migration inserts `prompt_v1_basic` so existing tests keep passing unchanged.

## Implementation Strategy

Schema first, then loop changes, then admin UI. Two of the four backend tasks (handoff triggers, prompt-config resolution) can be developed in parallel once the migration lands.

## Task Breakdown Preview

- 001 — Combined migration: Conversation.status + handoff_reason + PromptConfig + seed default
- 002 — Active-prompt resolver: `get_active_config` + cache + AgentLoop integration + prompt_version stamping
- 003 — Handoff triggers: detect repeated failures / iteration cap / human-request keywords / unsafe_action; flip status and store reason
- 004 — Handoff queue API: list endpoint + take-over + mark-resolved
- 005 — Handoff queue UI: /admin/handoff with action buttons and resolution note modal
- 006 — Agent loop early-return when conversation is not `active`

## Dependencies

- Reads `prompt_version` capture from Stream A once both are in main. Soft dep — if A isn't merged, the field is written but unread.
- Stream C reads `handoff_reason` + `prompt_version` for the quality report. Soft dep.

## Success Criteria (Technical)

- Two consecutive tool failures on a test conversation → status flips to `needs_human` and the row appears in `/admin/handoff` within one poll cycle.
- Toggling `PromptConfig.is_active` is reflected in the very next assistant turn's `prompt_version` field.
- Existing 154-test backend suite still passes via the no-config fallback.
- New tests: handoff-trigger matrix (5+ cases) + prompt-config resolution + early-return guard.

## Estimated Effort

- ~4 days for one developer.
- Critical path: 001 (migration) → 002 (resolver) / 003 (triggers) — must serialize since both edit agent/loop.py — → 004 (API) → 005 (UI).

## Tasks Created
- [ ] 001.md - Combined migration — Conversation.status + handoff fields + PromptConfig + seed (parallel: false)
- [ ] 002.md - Active-prompt resolver — get_active_config + AgentLoop wiring (parallel: false, conflicts with 003)
- [ ] 003.md - Handoff triggers + early-return guard (parallel: false, conflicts with 002)
- [ ] 004.md - Handoff queue API — list / take-over / mark-resolved (parallel: true)
- [ ] 005.md - Handoff queue UI — /admin/handoff (parallel: true)

Total tasks: 5
Parallel tasks: 2
Sequential tasks: 3
Estimated total effort: 22 hours
