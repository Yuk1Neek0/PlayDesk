"""
PlayDesk evaluation harness — replay labeled cases against the agent.

Reads ``knowledge-base/eval-cases.json`` (schema: docs/contracts/eval-format.md),
replays each case through the agent loop, checks the case's assertions, and
prints per-case PASS/FAIL plus aggregate accuracy.

The agent runs **in-process** against ``AgentLoop`` — the loop's ``run()``
return value is exactly the SSE ``done`` payload (message_id, text,
booking_id, iteration_count), so this is equivalent to driving the HTTP
endpoint but far easier to test.

The LLM client is pluggable: ``main()`` uses the real ``AnthropicClient``
(needs an API key); tests pass a scripted ``FakeLLMClient`` so CI needs no
secrets.

CLI:  python -m evals.run_evals      (from the backend/ directory)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# backend/evals/run_evals.py → parents[2] is the repo root.
EVAL_CASES_PATH = Path(__file__).resolve().parents[2] / "knowledge-base" / "eval-cases.json"

VALID_LABELS = {"should_book", "should_clarify", "should_refuse", "should_search_kb"}


def load_cases(path: Path | str | None = None) -> list[dict[str, Any]]:
    """Load and return the eval-case array from *path* (default: the contract location)."""
    cases_path = Path(path) if path is not None else EVAL_CASES_PATH
    with open(cases_path, encoding="utf-8") as fh:
        cases = json.load(fh)
    if not isinstance(cases, list):
        raise ValueError("eval-cases.json must be a JSON array of EvalCase objects")
    return cases


def check_assertions(
    assertions: dict[str, Any],
    result: dict[str, Any],
    tools_used: set[str],
) -> tuple[bool, str]:
    """
    Check one case's assertions against the agent's result.

    Pure function — no DB, no agent. Returns (passed, reason).

    `result` is the agent loop's return dict; `tools_used` is the set of tool
    names the agent called during the turn.
    """
    text = (result.get("text") or "").lower()
    booking_id = result.get("booking_id")

    tool_called = assertions.get("tool_called")
    if tool_called and tool_called not in tools_used:
        return False, (
            f"expected tool {tool_called!r} to be called; called: {sorted(tools_used) or 'none'}"
        )

    if assertions.get("booking_created") and booking_id is None:
        return False, "expected a booking to be created, but none was"

    if assertions.get("no_booking_created") and booking_id is not None:
        return False, f"expected no booking, but booking #{booking_id} was created"

    for substring in assertions.get("final_message_contains", []):
        if substring.lower() not in text:
            return False, f"final message is missing expected substring {substring!r}"

    for substring in assertions.get("final_message_excludes", []):
        if substring.lower() in text:
            return False, f"final message contains excluded substring {substring!r}"

    return True, "all assertions passed"


def run_case(case: dict[str, Any], llm_client: Any) -> dict[str, Any]:
    """
    Replay one EvalCase through the agent loop and evaluate its assertions.

    Returns {"id", "label", "passed", "reason"}.
    """
    from agent.loop import AgentLoop
    from core.models import Conversation, ConversationStatus, Message, MessageRole

    conversation = Conversation.objects.create(
        customer_identifier=f"eval-{case['id']}",
        status=ConversationStatus.ACTIVE,
    )

    # Replay every turn but the last as prior context.
    messages = case["messages"]
    for msg in messages[:-1]:
        role = MessageRole.USER if msg["role"] == "user" else MessageRole.ASSISTANT
        Message.objects.create(conversation=conversation, role=role, content=msg["content"])

    final_user_message = messages[-1]["content"]
    result = AgentLoop(llm_client=llm_client).run(conversation, final_user_message)

    tools_used = {
        name
        for name in Message.objects.filter(
            conversation=conversation, role=MessageRole.TOOL
        ).values_list("tool_call_data__tool_name", flat=True)
        if name
    }

    passed, reason = check_assertions(case.get("assertions", {}), result, tools_used)
    return {"id": case["id"], "label": case["label"], "passed": passed, "reason": reason}


def per_category(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Break a results list down by label.

    Returns ``{label: {"passed": int, "total": int, "accuracy": float}}``.
    The aggregate accuracy hides that one category (``should_book``) is the
    whole problem — this breakdown surfaces it (Issue #37).
    """
    breakdown: dict[str, dict[str, Any]] = {}
    for r in results:
        bucket = breakdown.setdefault(r["label"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        if r["passed"]:
            bucket["passed"] += 1
    for bucket in breakdown.values():
        bucket["accuracy"] = bucket["passed"] / bucket["total"] * 100.0
    return breakdown


def run_all(cases: list[dict[str, Any]], llm_client: Any) -> dict[str, Any]:
    """Run every case, print per-case results, and return an aggregate summary."""
    results = []
    for case in cases:
        outcome = run_case(case, llm_client)
        results.append(outcome)
        mark = "PASS" if outcome["passed"] else "FAIL"
        print(f"[{mark}] {outcome['id']} ({outcome['label']}) — {outcome['reason']}")

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    accuracy = (passed / total * 100.0) if total else 0.0

    categories = per_category(results)
    print("\nPer-category accuracy:")
    for label in sorted(categories):
        cat = categories[label]
        print(f"  {label:<18} {cat['passed']}/{cat['total']} ({cat['accuracy']:.1f}%)")
    print(f"\nAccuracy: {passed}/{total} ({accuracy:.1f}%)")
    return {
        "total": total,
        "passed": passed,
        "accuracy": accuracy,
        "categories": categories,
        "results": results,
    }


def main() -> int:
    """CLI entry point — runs every case against the real Anthropic-backed agent."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()

    from django.conf import settings

    from agent.llm_client import AnthropicClient

    cases = load_cases()
    client = AnthropicClient(
        api_key=getattr(settings, "ANTHROPIC_API_KEY", ""),
        model=getattr(settings, "ANTHROPIC_MODEL", "claude-opus-4-7"),
    )
    summary = run_all(cases, client)
    # Non-zero exit when any case failed, so CI / scripts can gate on it.
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
