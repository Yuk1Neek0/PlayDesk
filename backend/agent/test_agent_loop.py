"""
Tests for the hand-rolled agent loop (Issue #13).

All LLM calls are mocked via FakeLLMClient.
DB tests use pytest-django's `db` fixture.
"""

from __future__ import annotations

import pytest

from agent.llm_client import FakeLLMClient, LLMResponse, ToolCallRequest
from agent.loop import AgentLoop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_response(tool_name: str, args: dict) -> LLMResponse:
    return LLMResponse(
        text="",
        tool_calls=[ToolCallRequest(f"tc_{tool_name}", tool_name, args)],
        stop_reason="tool_use",
    )


def _make_text_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], stop_reason="end_turn")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def conversation(db):
    from core.models import Conversation, ConversationStatus

    return Conversation.objects.create(
        customer_identifier="test-user",
        status=ConversationStatus.ACTIVE,
    )


# ---------------------------------------------------------------------------
# Basic loop behaviour
# ---------------------------------------------------------------------------


class TestAgentLoopBasic:
    def test_plain_text_response_terminates(self, conversation):
        """If the LLM replies with plain text, the loop ends in one iteration."""
        events: list[tuple] = []
        fake = FakeLLMClient([_make_text_response("Hello, how can I help?")])
        loop = AgentLoop(llm_client=fake, event_callback=lambda t, p: events.append((t, p)))

        result = loop.run(conversation, "Hi")

        assert result["text"] == "Hello, how can I help?"
        assert result["iteration_count"] == 1
        # done event emitted
        done_events = [e for e in events if e[0] == "done"]
        assert len(done_events) == 1
        assert done_events[0][1]["text"] == "Hello, how can I help?"

    def test_tool_call_then_text(self, conversation):
        """Loop: tool call → plain text = 2 iterations."""
        events: list[tuple] = []
        fake = FakeLLMClient(
            [
                _make_tool_response(
                    "search_knowledge_base",
                    {"query": "outside food policy"},
                ),
                _make_text_response("Outside food is not allowed."),
            ]
        )
        loop = AgentLoop(llm_client=fake, event_callback=lambda t, p: events.append((t, p)))
        result = loop.run(conversation, "Can I bring outside food?")

        assert result["iteration_count"] == 2
        assert "not allowed" in result["text"]

        tool_starts = [e for e in events if e[0] == "tool_call_start"]
        tool_ends = [e for e in events if e[0] == "tool_call_end"]
        assert len(tool_starts) == 1
        assert tool_starts[0][1]["tool_name"] == "search_knowledge_base"
        assert len(tool_ends) == 1
        assert tool_ends[0][1]["error"] is None


class TestAgentLoopPersistence:
    def test_message_rows_created(self, conversation):
        """Every turn must be persisted as a Message row."""
        from core.models import Message, MessageRole

        fake = FakeLLMClient(
            [
                _make_tool_response(
                    "check_availability",
                    {
                        "resource_type": "console",
                        "date": "2026-05-23",
                        "time_range": ["20:00", "22:00"],
                        "party_size": 3,
                    },
                ),
                _make_text_response("Room is available!"),
            ]
        )
        loop = AgentLoop(llm_client=fake)
        loop.run(conversation, "Is there a PS5 free Saturday 8pm?")

        messages = list(Message.objects.filter(conversation=conversation).order_by("created_at"))
        roles = [m.role for m in messages]

        assert MessageRole.USER in roles
        assert MessageRole.ASSISTANT in roles
        assert MessageRole.TOOL in roles

    def test_tool_call_data_jsonb(self, conversation):
        """Tool result messages must have non-null tool_call_data."""
        from core.models import Message, MessageRole

        fake = FakeLLMClient(
            [
                _make_tool_response("search_knowledge_base", {"query": "cancellation policy"}),
                _make_text_response("You can cancel up to 24 hours in advance."),
            ]
        )
        loop = AgentLoop(llm_client=fake)
        loop.run(conversation, "What is your cancellation policy?")

        tool_msgs = Message.objects.filter(conversation=conversation, role=MessageRole.TOOL)
        assert tool_msgs.exists()
        for msg in tool_msgs:
            assert msg.tool_call_data is not None
            assert "tool_call_id" in msg.tool_call_data
            assert "tool_name" in msg.tool_call_data


class TestAgentLoopIterationCap:
    def test_iteration_cap_triggers_handoff(self, conversation):
        """After AGENT_MAX_ITERATIONS, the loop must emit a graceful handoff."""
        events: list[tuple] = []

        # Script one more response than the cap (loop will stop at cap)
        script = [_make_tool_response("search_knowledge_base", {"query": "q"}) for _ in range(10)]
        fake = FakeLLMClient(script)
        loop = AgentLoop(
            llm_client=fake,
            max_iterations=3,
            event_callback=lambda t, p: events.append((t, p)),
        )
        result = loop.run(conversation, "Keep searching…")

        assert result["iteration_count"] == 3
        assert "human teammate" in result["text"].lower() or "hand" in result["text"].lower()

        error_events = [e for e in events if e[0] == "error"]
        assert any(e[1]["code"] == "iteration_limit" for e in error_events)

    def test_iteration_cap_persists_final_message(self, conversation):
        """Handoff message must be persisted even when the cap is hit."""
        from core.models import Message, MessageRole

        script = [_make_tool_response("search_knowledge_base", {"query": "q"}) for _ in range(5)]
        fake = FakeLLMClient(script)
        loop = AgentLoop(llm_client=fake, max_iterations=2)
        loop.run(conversation, "Repeat")

        last_assistant = (
            Message.objects.filter(conversation=conversation, role=MessageRole.ASSISTANT)
            .order_by("-created_at")
            .first()
        )
        assert last_assistant is not None
        assert "human" in last_assistant.content.lower() or "hand" in last_assistant.content.lower()


class TestAgentLoopToolFailure:
    def test_tool_failure_is_structured_error_not_raised(self, conversation):
        """A bad tool call must not raise — the error goes back to the LLM."""
        events: list[tuple] = []

        fake = FakeLLMClient(
            [
                LLMResponse(
                    text="",
                    tool_calls=[ToolCallRequest("tc_bad", "nonexistent_tool", {})],
                    stop_reason="tool_use",
                ),
                _make_text_response("I encountered an issue but recovered."),
            ]
        )
        loop = AgentLoop(llm_client=fake, event_callback=lambda t, p: events.append((t, p)))
        # Must not raise
        result = loop.run(conversation, "Do something")

        assert result["text"] is not None
        end_events = [e for e in events if e[0] == "tool_call_end"]
        assert len(end_events) == 1
        assert end_events[0][1]["error"] is not None
        assert "Unknown tool" in end_events[0][1]["error"]


class TestAgentLoopRagInjection:
    def test_rag_chunks_injected_into_system_prompt(self, conversation):
        """RAG chunks must appear in the system prompt sent to the LLM."""
        call_log: list[dict] = []

        def capture(_t: str, _p: dict) -> None:
            pass

        fake = FakeLLMClient([_make_text_response("Sure!")])
        # Intercept the complete call to inspect the system prompt
        original_complete = fake.complete

        def spy_complete(system, messages, tools):
            call_log.append({"system": system})
            return original_complete(system, messages, tools)

        fake.complete = spy_complete  # type: ignore[method-assign]

        loop = AgentLoop(
            llm_client=fake,
            rag_chunks=["CHUNK: You can bring drinks from our counter."],
            event_callback=capture,
        )
        loop.run(conversation, "Food policy?")

        assert call_log
        assert "CHUNK: You can bring drinks from our counter." in call_log[0]["system"]
