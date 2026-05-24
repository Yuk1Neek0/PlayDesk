"""Tests for the evaluation harness (Issue #24)."""

from __future__ import annotations

import pytest

from agent.llm_client import FakeLLMClient, LLMResponse, ToolCallRequest
from evals.run_evals import (
    VALID_LABELS,
    check_assertions,
    load_cases,
    per_category,
    run_case,
)


def _result(text: str = "", booking_id: int | None = None) -> dict:
    return {"text": text, "booking_id": booking_id, "message_id": 1, "iteration_count": 1}


# ---------------------------------------------------------------------------
# check_assertions — pure, no DB
# ---------------------------------------------------------------------------


class TestCheckAssertions:
    def test_all_assertions_pass(self):
        passed, reason = check_assertions(
            {
                "tool_called": "create_booking",
                "booking_created": True,
                "final_message_contains": ["confirmed"],
            },
            _result("Your booking is confirmed!", booking_id=7),
            {"create_booking"},
        )
        assert passed
        assert "passed" in reason

    def test_tool_not_called_fails(self):
        passed, reason = check_assertions({"tool_called": "create_booking"}, _result("hi"), set())
        assert not passed
        assert "create_booking" in reason

    def test_null_tool_called_is_skipped(self):
        passed, _ = check_assertions({"tool_called": None}, _result("hi"), set())
        assert passed

    def test_booking_expected_but_missing_fails(self):
        passed, reason = check_assertions(
            {"booking_created": True}, _result("ok", booking_id=None), {"create_booking"}
        )
        assert not passed
        assert "booking" in reason

    def test_no_booking_violated_fails(self):
        passed, reason = check_assertions(
            {"no_booking_created": True}, _result("done", booking_id=12), set()
        )
        assert not passed
        assert "12" in reason

    def test_missing_substring_fails(self):
        passed, reason = check_assertions(
            {"final_message_contains": ["confirmed"]}, _result("all set"), set()
        )
        assert not passed
        assert "confirmed" in reason

    def test_excluded_substring_fails(self):
        passed, reason = check_assertions(
            {"final_message_excludes": ["error"]}, _result("an error occurred"), set()
        )
        assert not passed
        assert "error" in reason


# ---------------------------------------------------------------------------
# eval-cases.json conforms to the contract
# ---------------------------------------------------------------------------


def test_eval_cases_file_is_valid():
    cases = load_cases()
    assert 10 <= len(cases) <= 15

    seen_ids: set[str] = set()
    for case in cases:
        assert case["id"] and case["id"] not in seen_ids
        seen_ids.add(case["id"])
        assert case["description"]
        assert case["lang"] in {"en", "zh"}
        assert case["label"] in VALID_LABELS
        assert isinstance(case["messages"], list) and case["messages"]
        assert case["messages"][-1]["role"] == "user"
        assert isinstance(case["assertions"], dict)


# ---------------------------------------------------------------------------
# run_case — end-to-end against the agent loop with a scripted fake LLM
# ---------------------------------------------------------------------------


class TestRunCase:
    @pytest.fixture(autouse=True)
    def _seed_store(self, db):
        from core.models import Store

        Store.objects.get_or_create(
            name="Eval Store", defaults={"timezone": "UTC", "business_hours": {}}
        )

    def test_search_kb_case_passes(self, db):
        case = {
            "id": "t-kb",
            "label": "should_search_kb",
            "lang": "en",
            "messages": [{"role": "user", "content": "Can I bring food?"}],
            "assertions": {
                "tool_called": "search_knowledge_base",
                "no_booking_created": True,
            },
        }
        fake = FakeLLMClient(
            [
                LLMResponse(
                    text="",
                    tool_calls=[ToolCallRequest("tc1", "search_knowledge_base", {"query": "food"})],
                    stop_reason="tool_use",
                ),
                LLMResponse(
                    text="Outside food is not permitted.",
                    tool_calls=[],
                    stop_reason="end_turn",
                ),
            ]
        )
        outcome = run_case(case, fake)
        assert outcome["passed"], outcome["reason"]

    def test_failing_case_reports_reason(self, db):
        case = {
            "id": "t-fail",
            "label": "should_book",
            "lang": "en",
            "messages": [{"role": "user", "content": "Book a PS5 now"}],
            "assertions": {"tool_called": "create_booking", "booking_created": True},
        }
        # The fake just talks — no tool call, no booking created.
        fake = FakeLLMClient(
            [LLMResponse(text="Sure, when?", tool_calls=[], stop_reason="end_turn")]
        )
        outcome = run_case(case, fake)
        assert not outcome["passed"]
        assert "create_booking" in outcome["reason"]

    def test_per_category_breakdown(self):
        results = [
            {"label": "should_book", "passed": True},
            {"label": "should_book", "passed": False},
            {"label": "should_refuse", "passed": True},
        ]
        breakdown = per_category(results)
        assert breakdown["should_book"] == {"passed": 1, "total": 2, "accuracy": 50.0}
        assert breakdown["should_refuse"] == {"passed": 1, "total": 1, "accuracy": 100.0}

    def test_multi_turn_context_is_replayed(self, db):
        case = {
            "id": "t-multi",
            "label": "should_search_kb",
            "lang": "en",
            "messages": [
                {"role": "user", "content": "I have a question"},
                {"role": "assistant", "content": "Sure, what is it?"},
                {"role": "user", "content": "What are your hours?"},
            ],
            "assertions": {"tool_called": "search_knowledge_base"},
        }
        fake = FakeLLMClient(
            [
                LLMResponse(
                    text="",
                    tool_calls=[
                        ToolCallRequest("tc1", "search_knowledge_base", {"query": "hours"})
                    ],
                    stop_reason="tool_use",
                ),
                LLMResponse(text="We are open 10am–1am.", tool_calls=[], stop_reason="end_turn"),
            ]
        )
        outcome = run_case(case, fake)
        assert outcome["passed"], outcome["reason"]
