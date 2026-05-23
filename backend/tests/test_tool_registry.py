"""
Tests for the agent tool registry (Issue #5).

These tests need no database — they only exercise Pydantic validation and
the registry machinery.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_tools.registry import get_tool, list_tools
from agent_tools.schemas import (
    CheckAvailabilityInput,
    CreateBookingInput,
    SearchKnowledgeBaseInput,
)

EXPECTED_TOOLS = {
    "search_knowledge_base",
    "check_availability",
    "get_resource_details",
    "create_booking",
    "modify_booking",
    "cancel_booking",
}


class TestRegistryDiscovery:
    def test_all_expected_tools_registered(self):
        assert set(list_tools()) == EXPECTED_TOOLS

    def test_get_tool_returns_entry(self):
        for name in EXPECTED_TOOLS:
            entry = get_tool(name)
            assert entry.name == name
            assert entry.input_schema is not None
            assert entry.output_schema is not None
            assert callable(entry.fn)

    def test_get_unknown_tool_raises_key_error(self):
        with pytest.raises(KeyError):
            get_tool("nonexistent_tool")


class TestToolStubOutputsValidateAgainstSchema:
    """Each stub must return data that is valid per its output schema."""

    def test_search_knowledge_base(self):
        entry = get_tool("search_knowledge_base")
        inp = entry.input_schema(query="outside food policy")
        out = entry.fn(inp)
        validated = entry.output_schema.model_validate(out.model_dump())
        assert len(validated.results) >= 1

    def test_check_availability(self):
        entry = get_tool("check_availability")
        inp = entry.input_schema(
            resource_type="console",
            date="2026-05-22",
            time_range=("20:00", "22:00"),
            party_size=2,
        )
        out = entry.fn(inp)
        validated = entry.output_schema.model_validate(out.model_dump())
        assert isinstance(validated.available, list)
        assert isinstance(validated.suggestions, list)

    def test_check_availability_has_suggestions_field(self):
        """Spec requirement: output must carry both available and suggestions."""
        from agent_tools.schemas import CheckAvailabilityOutput

        fields = CheckAvailabilityOutput.model_fields
        assert "available" in fields
        assert "suggestions" in fields

    def test_get_resource_details(self):
        entry = get_tool("get_resource_details")
        inp = entry.input_schema(resource_type="console")
        out = entry.fn(inp)
        validated = entry.output_schema.model_validate(out.model_dump())
        assert len(validated.resources) >= 1

    def test_create_booking_success(self):
        entry = get_tool("create_booking")
        inp = entry.input_schema(
            resource_id=1,
            start_time=datetime(2026, 5, 22, 20, 0, tzinfo=UTC),
            duration_minutes=120,
            customer_name="Alice",
            customer_phone="+86-138-0000-0001",
        )
        out = entry.fn(inp)
        validated = entry.output_schema.model_validate(out.model_dump())
        # Stub always succeeds; result must be a CreateBookingSuccess
        from agent_tools.schemas import CreateBookingSuccess

        assert isinstance(validated.result, CreateBookingSuccess)
        assert validated.result.success is True
        assert validated.result.booking_id is not None

    def test_create_booking_output_models_conflict_error(self):
        """Spec requirement: output schema must be capable of modelling a conflict error."""
        from agent_tools.schemas import BookingConflictError, CreateBookingOutput

        conflict = BookingConflictError(
            message="Slot taken",
            conflicting_start=datetime(2026, 5, 22, 20, 0, tzinfo=UTC),
            conflicting_end=datetime(2026, 5, 22, 22, 0, tzinfo=UTC),
        )
        out = CreateBookingOutput(result=conflict)
        assert out.result.error == "conflict"

    def test_modify_booking(self):
        entry = get_tool("modify_booking")
        inp = entry.input_schema(
            booking_id=1001,
            new_start_time=datetime(2026, 5, 22, 21, 0, tzinfo=UTC),
            new_duration_minutes=90,
        )
        out = entry.fn(inp)
        validated = entry.output_schema.model_validate(out.model_dump())
        assert validated.success is True

    def test_cancel_booking(self):
        entry = get_tool("cancel_booking")
        inp = entry.input_schema(booking_id=1001)
        out = entry.fn(inp)
        validated = entry.output_schema.model_validate(out.model_dump())
        assert validated.success is True
        assert validated.booking_id == 1001


class TestInputSchemaValidation:
    """Confirm Pydantic rejects bad input."""

    def test_search_kb_requires_query(self):
        with pytest.raises(ValidationError):
            SearchKnowledgeBaseInput()

    def test_check_availability_requires_party_size(self):
        with pytest.raises(ValidationError):
            CheckAvailabilityInput(
                resource_type="console",
                date="2026-05-22",
                time_range=("20:00", "22:00"),
                # party_size omitted
            )

    def test_create_booking_min_duration(self):
        with pytest.raises(ValidationError):
            CreateBookingInput(
                resource_id=1,
                start_time=datetime(2026, 5, 22, 20, 0, tzinfo=UTC),
                duration_minutes=15,  # below 30-minute minimum
                customer_name="Bob",
                customer_phone="+14165550123",
            )
