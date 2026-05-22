# Verification Record — Issue #33 (Stream B: agent loop & RAG)

Verified: 2026-05-22, against the live `docker compose` stack with real LLM calls.
Dev plan sections: §1.3 (agent loop), §1.4 (RAG), §1.5 (agent tools).

## Acceptance criteria

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Single NL message completes a booking | ✅ PASS | Conversation 25 — "Saturday 8pm, PS5 for 3 people, ~2h" → `check_availability` → `get_resource_details` → `create_booking`; Booking id 11 in DB (2026-05-23 20:00–22:00, `source=agent`) |
| 2 | RAG-vs-SQL routing | ✅ PASS | "Can I bring outside food?" → `search_knowledge_base`; "Is room 3 free at 8pm tomorrow?" → `check_availability`; never reversed (zh case also verified) |
| 3 | Correct tool per query type | ✅ PASS | `get_resource_details`, `create_booking`, `modify_booking`, `cancel_booking` each selected correctly in smoke conversations |
| 4 | `Message` table holds full coherent trace | ✅ PASS | Conv 25 trace is ordered user / assistant / tool / assistant; JSONB `tool_call_data` carries payloads + results + error field |
| 5 | 6-iteration cap → graceful human handoff | ✅ PASS | Default `AGENT_MAX_ITERATIONS=6`; loop stops at 6, emits handoff message + `iteration_limit` error, persists the final row |
| 6 | Tool failures → structured error to the LLM | ✅ PASS | `_execute_tool` catches unknown-tool and Pydantic validation errors, returns `(tc, None, error)` instead of raising to the user |

**Result: 6 / 6 functional acceptance criteria PASS.**

## Bugs found and fixed in-stream

### BUG-33-1 — agent had no notion of the current date
The agent's system prompt carried no current date, so the LLM guessed arbitrary
past dates for relative expressions ("Saturday" → 2025-11-15, "tomorrow" →
2025-01-01), breaking `check_availability` / `create_booking` for any
natural-language date — the single most common booking phrasing.

**Fix:** added `date_directive()` to `backend/agent/prompt.py` and appended it in
`AgentLoop._build_system_prompt` (`backend/agent/loop.py`). Both files within
Stream B scope; no shared-file changes. Committed locally as `777d552`
("Issue #33: inject current date into agent system prompt"), not pushed.

## Regression check

Post-fix, inside the backend container:
- `pytest agent/` — 37 passed
- `pytest tests/test_rag.py` — 17 passed
- `pytest tests/test_agent_tools.py` — 25 passed
- `pytest tests/test_tool_registry.py` — 14 passed
- **Total: 93 passed, 0 failed**
- `ruff check` + `ruff format --check` — clean on both changed files

## Notes for #36 (integration & sign-off)

- `pytest` / `ruff` are NOT preinstalled in the running backend image — the
  Dockerfile installs `requirements.txt` only, not `requirements-dev.txt`. They
  had to be `pip install`-ed inside the container to run the regression suite.
  Consider whether the image should bake in dev tooling, or whether CI handles
  it separately.
- Only `backend/agent/loop.py` and `backend/agent/prompt.py` were staged/committed
  by this stream. Other modified files in `git status` belong to sibling streams.
- This stream's `verification-record.md` and `progress.md` were authored by the
  parent agent — the background stream agent was blocked from creating new files
  on the host.
