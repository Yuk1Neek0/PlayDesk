# Evaluation Set Format

This document defines the labeled test-conversation JSON schema used by the
PlayDesk evaluation harness (§2.1 of the dev plan).

---

## Purpose

The eval set validates that the AI agent:
- calls the correct tool for each query type
- books, clarifies, refuses, or searches the knowledge base as expected
- produces on-topic final responses

---

## File location

Evaluation cases are stored as a single JSON array in:

```
knowledge-base/eval-cases.json
```

---

## Top-level schema

```json
[
  { /* EvalCase */ },
  { /* EvalCase */ },
  ...
]
```

A valid eval file is a JSON array of 10–15 `EvalCase` objects.

---

## `EvalCase` object

```json
{
  "id": "eval-001",
  "description": "Simple booking request with enough detail to complete in one turn",
  "lang": "en",
  "messages": [
    { "role": "user", "content": "Book PS5 Station A for Saturday 8pm, 2 hours, Alice Wang, +86-138-0000-0001" }
  ],
  "label": "should_book",
  "assertions": {
    "tool_called": "create_booking",
    "booking_created": true,
    "final_message_contains": ["booking", "confirmed"]
  },
  "notes": "All required fields present; agent should book without clarification."
}
```

### Field reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` | Yes | Unique case ID, e.g. `"eval-001"`. Used in pass/fail output. |
| `description` | `string` | Yes | One-line human description of what this case tests. |
| `lang` | `string` | Yes | `"en"` or `"zh"`. The harness sends the user message in this language and expects a response in the same language. |
| `messages` | `array<Message>` | Yes | Ordered conversation turns to replay. Usually a single user turn; multi-turn cases carry prior context. |
| `label` | `string` | Yes | Expected high-level behavior (see label table below). |
| `assertions` | `Assertions` | Yes | Machine-checkable conditions to assert after the agent responds. |
| `notes` | `string` | No | Free-text rationale; not evaluated. |

---

## `Message` object

```json
{ "role": "user", "content": "Can I bring food?" }
```

| Field | Type | Values |
|-------|------|--------|
| `role` | `string` | `"user"` \| `"assistant"` |
| `content` | `string` | Message text |

Prior assistant turns are included when testing multi-turn reasoning.

---

## Label values

| Label | When to use |
|-------|-------------|
| `should_book` | The agent has enough information to complete a booking and should do so |
| `should_clarify` | The request is ambiguous or incomplete; the agent must ask a follow-up question before booking |
| `should_refuse` | The agent must decline (e.g., outside business hours, unsupported request, age-restricted content) |
| `should_search_kb` | The query is a policy / menu / FAQ question; the agent must call `search_knowledge_base` and answer from KB — no booking |

---

## `Assertions` object

```json
{
  "tool_called": "create_booking",
  "booking_created": true,
  "final_message_contains": ["booking", "confirmed"],
  "final_message_excludes": [],
  "no_booking_created": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `tool_called` | `string \| null` | The tool the agent must call at least once. `null` means no specific tool is required. |
| `booking_created` | `boolean` | `true` if a booking row must exist after the conversation. |
| `no_booking_created` | `boolean` | `true` if a booking must NOT be created (e.g., clarify / refuse cases). Mutually exclusive with `booking_created: true`. |
| `final_message_contains` | `array<string>` | Lowercase substrings that must appear in the final assistant message. |
| `final_message_excludes` | `array<string>` | Lowercase substrings that must NOT appear in the final assistant message. |

All assertion fields are optional; omit rather than set to `null` or empty to
keep cases readable.

---

## Eval harness contract

The Python eval script (`backend/evals/run_evals.py`) reads `eval-cases.json`
and for each case:

1. Creates a fresh conversation via `POST /api/conversations/`
2. Replays each message in `messages` (sending all but the last as context,
   then sending the final user message to the live endpoint)
3. Collects the `done` SSE event
4. Checks all assertions and records `PASS` / `FAIL` with a reason string
5. Prints per-case results and an aggregate accuracy percentage

---

## Example cases (illustrative)

```json
[
  {
    "id": "eval-001",
    "description": "Complete booking — all details provided",
    "lang": "en",
    "messages": [
      { "role": "user", "content": "Book PS5 Station A on Saturday 2026-06-06 from 8pm to 10pm, name Alice Wang, phone +86-138-0000-0001" }
    ],
    "label": "should_book",
    "assertions": {
      "tool_called": "create_booking",
      "booking_created": true,
      "final_message_contains": ["booking"]
    }
  },
  {
    "id": "eval-002",
    "description": "Ambiguous booking — missing date",
    "lang": "en",
    "messages": [
      { "role": "user", "content": "I want to book a PS5 at 8pm for 2 hours" }
    ],
    "label": "should_clarify",
    "assertions": {
      "tool_called": null,
      "no_booking_created": true,
      "final_message_contains": ["date", "which"]
    }
  },
  {
    "id": "eval-003",
    "description": "Policy question — outside food",
    "lang": "en",
    "messages": [
      { "role": "user", "content": "Can I bring my own snacks?" }
    ],
    "label": "should_search_kb",
    "assertions": {
      "tool_called": "search_knowledge_base",
      "no_booking_created": true
    }
  },
  {
    "id": "eval-004",
    "description": "Refusal — request outside business hours",
    "lang": "en",
    "messages": [
      { "role": "user", "content": "Can I book a room for 3am next Tuesday?" }
    ],
    "label": "should_refuse",
    "assertions": {
      "no_booking_created": true,
      "final_message_contains": ["hours", "open"]
    }
  },
  {
    "id": "eval-005",
    "description": "Complete booking in Chinese",
    "lang": "zh",
    "messages": [
      { "role": "user", "content": "我想预订PS5 A台，本周六晚上8点到10点，姓名王芳，电话13800000002" }
    ],
    "label": "should_book",
    "assertions": {
      "tool_called": "create_booking",
      "booking_created": true
    }
  }
]
```
