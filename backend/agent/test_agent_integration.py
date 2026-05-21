"""
Integration tests for the agent system prompt and end-to-end scenarios (Issue #15).

All LLM calls are mocked. DB is required (pytest-django).
Tests assert:
  1. Natural-language booking → agent calls the right tools and completes a booking.
  2. "Can I bring outside food?" → routes to search_knowledge_base, not SQL tools.
  3. "Is room 3 free at 8pm tomorrow?" → routes to check_availability, never RAG.
  4. Message table forms a complete, readable reasoning trace.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent.llm_client import FakeLLMClient, LLMResponse, ToolCallRequest
from agent.loop import AgentLoop
from agent.prompt import SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def conversation(db):
    from core.models import Conversation, ConversationStatus

    return Conversation.objects.create(
        customer_identifier="integration-test",
        status=ConversationStatus.ACTIVE,
    )


@pytest.fixture()
def booking_resource(db):
    """A bookable PS5 console resource for the booking-scenario tests."""
    from core.models import Resource, Store

    store = Store.objects.create(name="PlayDesk Test Lounge", timezone="UTC", business_hours={})
    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Station 1",
        capacity=4,
        price_per_hour="58.00",
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _booking_script(resource_id: int = 1) -> list[LLMResponse]:
    """
    Scripted LLM responses that simulate a complete booking flow:
    1. get_resource_details to find a PS5 console
    2. check_availability to verify the Saturday 8pm slot
    3. create_booking with the confirmed details
    4. Final confirmation text
    """
    return [
        # Turn 1: get resource details
        LLMResponse(
            text="",
            tool_calls=[
                ToolCallRequest(
                    "tc_get_details",
                    "get_resource_details",
                    {"resource_type": "console"},
                )
            ],
            stop_reason="tool_use",
        ),
        # Turn 2: check availability
        LLMResponse(
            text="",
            tool_calls=[
                ToolCallRequest(
                    "tc_check_avail",
                    "check_availability",
                    {
                        "resource_type": "console",
                        "date": "2026-05-23",
                        "time_range": ["20:00", "22:00"],
                        "party_size": 3,
                    },
                )
            ],
            stop_reason="tool_use",
        ),
        # Turn 3: create booking
        LLMResponse(
            text="",
            tool_calls=[
                ToolCallRequest(
                    "tc_create_booking",
                    "create_booking",
                    {
                        "resource_id": resource_id,
                        "start_time": datetime(2026, 5, 23, 20, 0, tzinfo=UTC).isoformat(),
                        "duration_minutes": 120,
                        "customer_name": "Alice",
                        "customer_phone": "+86-138-0000-0001",
                    },
                )
            ],
            stop_reason="tool_use",
        ),
        # Turn 4: final confirmation text
        LLMResponse(
            text=(
                "Great news! I've booked PS5 Station 1 for you on Saturday 8–10 pm. "
                "Your booking ID is 1001. See you then!"
            ),
            tool_calls=[],
            stop_reason="end_turn",
        ),
    ]


# ---------------------------------------------------------------------------
# Test 1: Booking scenario
# ---------------------------------------------------------------------------


class TestBookingScenario:
    def test_saturday_ps5_booking_completes(self, conversation, booking_resource):
        """
        "Saturday 8pm, PS5 for 3, ~2 hours" → agent completes a booking.

        Asserts:
          - create_booking is called (booking_id extracted)
          - check_availability is called
          - Final text references the booking
          - booking_id is set in the result
        """
        events: list[tuple] = []
        fake = FakeLLMClient(_booking_script(booking_resource.pk))
        loop = AgentLoop(llm_client=fake, event_callback=lambda t, p: events.append((t, p)))

        result = loop.run(conversation, "Saturday 8pm, PS5 for 3, around 2 hours")

        # booking_id is extracted from the create_booking tool result
        assert result["booking_id"] is not None
        assert isinstance(result["booking_id"], int)

        # check_availability and create_booking must have been called
        tool_starts = [e[1]["tool_name"] for e in events if e[0] == "tool_call_start"]
        assert "check_availability" in tool_starts
        assert "create_booking" in tool_starts

        # Final text mentions the booking
        assert "1001" in result["text"] or "booked" in result["text"].lower()

    def test_booking_trace_in_message_table(self, conversation):
        """
        After the booking conversation, Message rows must form a complete,
        readable trace: user → assistant(tool) × N → tool_results × N → assistant(text).
        """
        from core.models import Message, MessageRole

        fake = FakeLLMClient(_booking_script())
        loop = AgentLoop(llm_client=fake)
        loop.run(conversation, "Saturday 8pm, PS5 for 3, around 2 hours")

        messages = list(Message.objects.filter(conversation=conversation).order_by("created_at"))
        roles = [m.role for m in messages]

        # Must have: user, at least one TOOL result, and a final ASSISTANT text
        assert MessageRole.USER in roles
        assert MessageRole.TOOL in roles
        assert MessageRole.ASSISTANT in roles

        # Last message must be the assistant's plain-text confirmation
        last = messages[-1]
        assert last.role == MessageRole.ASSISTANT
        assert last.content != ""
        assert (
            last.tool_call_data is None or last.tool_call_data.get("type") != "assistant_with_tools"
        )

        # All tool messages have JSONB payloads
        tool_msgs = [m for m in messages if m.role == MessageRole.TOOL]
        assert len(tool_msgs) == 3  # one per tool call in the script
        for msg in tool_msgs:
            assert msg.tool_call_data is not None
            assert msg.tool_call_data.get("tool_name") is not None


# ---------------------------------------------------------------------------
# Test 2: Knowledge base routing
# ---------------------------------------------------------------------------


class TestKnowledgeBaseRouting:
    def test_outside_food_routes_to_kb(self, conversation):
        """
        "Can I bring outside food?" must route to search_knowledge_base, not a SQL tool.
        """
        events: list[tuple] = []
        fake = FakeLLMClient(
            [
                LLMResponse(
                    text="",
                    tool_calls=[
                        ToolCallRequest(
                            "tc_kb",
                            "search_knowledge_base",
                            {"query": "outside food policy"},
                        )
                    ],
                    stop_reason="tool_use",
                ),
                LLMResponse(
                    text="Outside food and beverages are not permitted in gaming areas.",
                    tool_calls=[],
                    stop_reason="end_turn",
                ),
            ]
        )
        loop = AgentLoop(llm_client=fake, event_callback=lambda t, p: events.append((t, p)))
        result = loop.run(conversation, "Can I bring outside food?")

        tool_calls_made = [e[1]["tool_name"] for e in events if e[0] == "tool_call_start"]

        # Must use search_knowledge_base
        assert "search_knowledge_base" in tool_calls_made

        # Must NOT use SQL tools
        sql_tools = {"check_availability", "create_booking", "modify_booking", "cancel_booking"}
        assert not sql_tools.intersection(tool_calls_made), (
            f"SQL tool(s) called for a policy question: {sql_tools.intersection(tool_calls_made)}"
        )

        assert "outside food" in result["text"].lower() or "not permitted" in result["text"].lower()

    def test_outside_food_persisted_correctly(self, conversation):
        """Tool result for KB query must be persisted."""
        from core.models import Message, MessageRole

        fake = FakeLLMClient(
            [
                LLMResponse(
                    text="",
                    tool_calls=[
                        ToolCallRequest("tc_kb", "search_knowledge_base", {"query": "outside food"})
                    ],
                    stop_reason="tool_use",
                ),
                LLMResponse(text="No outside food allowed.", tool_calls=[], stop_reason="end_turn"),
            ]
        )
        loop = AgentLoop(llm_client=fake)
        loop.run(conversation, "Can I bring outside food?")

        tool_msgs = Message.objects.filter(conversation=conversation, role=MessageRole.TOOL)
        assert tool_msgs.exists()
        kb_tool = tool_msgs.filter(tool_call_data__tool_name="search_knowledge_base")
        assert kb_tool.exists()


# ---------------------------------------------------------------------------
# Test 3: Availability query routing
# ---------------------------------------------------------------------------


class TestAvailabilityRouting:
    def test_room_availability_routes_to_check_availability(self, conversation):
        """
        "Is room 3 free at 8pm tomorrow?" must route to check_availability, never RAG.
        """
        events: list[tuple] = []
        fake = FakeLLMClient(
            [
                LLMResponse(
                    text="",
                    tool_calls=[
                        ToolCallRequest(
                            "tc_avail",
                            "check_availability",
                            {
                                "resource_type": "room",
                                "date": "2026-05-22",
                                "time_range": ["20:00", "22:00"],
                                "party_size": 1,
                            },
                        )
                    ],
                    stop_reason="tool_use",
                ),
                LLMResponse(
                    text="Room 3 is available at 8pm tomorrow!",
                    tool_calls=[],
                    stop_reason="end_turn",
                ),
            ]
        )
        loop = AgentLoop(llm_client=fake, event_callback=lambda t, p: events.append((t, p)))
        result = loop.run(conversation, "Is room 3 free at 8pm tomorrow?")

        tool_calls_made = [e[1]["tool_name"] for e in events if e[0] == "tool_call_start"]

        # Must use check_availability
        assert "check_availability" in tool_calls_made

        # Must NOT use search_knowledge_base
        assert "search_knowledge_base" not in tool_calls_made, (
            "RAG called for an availability question — violates the RAG-vs-SQL partition rule."
        )

        assert "available" in result["text"].lower()

    def test_availability_result_has_no_rag_in_trace(self, conversation):
        """Message trace must not contain a search_knowledge_base tool call."""
        from core.models import Message, MessageRole

        fake = FakeLLMClient(
            [
                LLMResponse(
                    text="",
                    tool_calls=[
                        ToolCallRequest(
                            "tc_avail",
                            "check_availability",
                            {
                                "resource_type": "room",
                                "date": "2026-05-22",
                                "time_range": ["20:00", "22:00"],
                                "party_size": 1,
                            },
                        )
                    ],
                    stop_reason="tool_use",
                ),
                LLMResponse(text="Room is free!", tool_calls=[], stop_reason="end_turn"),
            ]
        )
        loop = AgentLoop(llm_client=fake)
        loop.run(conversation, "Is room 3 free at 8pm tomorrow?")

        tool_msgs = list(Message.objects.filter(conversation=conversation, role=MessageRole.TOOL))
        for msg in tool_msgs:
            assert msg.tool_call_data
            assert msg.tool_call_data.get("tool_name") != "search_knowledge_base"


# ---------------------------------------------------------------------------
# Test 4: System prompt content
# ---------------------------------------------------------------------------


class TestSystemPrompt:
    def test_system_prompt_contains_rag_vs_sql_partition_rule(self):
        """The system prompt must contain the RAG-vs-SQL partition instruction."""
        assert "search_knowledge_base" in SYSTEM_PROMPT
        assert "check_availability" in SYSTEM_PROMPT
        # RAG for unstructured, SQL for structured
        assert "unstructured" in SYSTEM_PROMPT.lower() or "policy" in SYSTEM_PROMPT.lower()
        assert "availability" in SYSTEM_PROMPT.lower()

    def test_system_prompt_prohibits_rag_for_availability(self):
        """Prompt must explicitly forbid using RAG for availability queries."""
        lower = SYSTEM_PROMPT.lower()
        assert "never use" in lower or "do not use" in lower or "never" in lower

    def test_system_prompt_injected_into_llm_calls(self, conversation):
        """The system prompt must be passed to the LLM on every call."""
        call_log: list[dict] = []
        original_init_script = [LLMResponse(text="ok", tool_calls=[], stop_reason="end_turn")]
        fake = FakeLLMClient(original_init_script)

        original_complete = fake.complete

        def spy(system, messages, tools):
            call_log.append({"system": system})
            return original_complete(system, messages, tools)

        fake.complete = spy  # type: ignore[method-assign]

        loop = AgentLoop(llm_client=fake)
        loop.run(conversation, "Hello")

        assert call_log
        # System prompt core content must be present
        assert "PlayDesk" in call_log[0]["system"]
        assert "search_knowledge_base" in call_log[0]["system"]
