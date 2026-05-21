"""
Tool registry for PlayDesk agent.

Maps tool names to their (input_schema, output_schema, callable) tuples.
The agent loop uses this to:
  1. Build the LLM tool-use manifest (from input schemas).
  2. Dispatch tool calls by name.
  3. Validate tool outputs before returning to the LLM.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from pydantic import BaseModel

from .schemas import (
    CancelBookingInput,
    CancelBookingOutput,
    CheckAvailabilityInput,
    CheckAvailabilityOutput,
    CreateBookingInput,
    CreateBookingOutput,
    GetResourceDetailsInput,
    GetResourceDetailsOutput,
    ModifyBookingInput,
    ModifyBookingOutput,
    SearchKnowledgeBaseInput,
    SearchKnowledgeBaseOutput,
)
from .stubs import (
    cancel_booking,
    check_availability,
    create_booking,
    get_resource_details,
    modify_booking,
    search_knowledge_base,
)


class ToolEntry(NamedTuple):
    """Registry entry for a single tool."""

    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    fn: Callable[[Any], Any]


_REGISTRY: dict[str, ToolEntry] = {}


def _register(entry: ToolEntry) -> None:
    _REGISTRY[entry.name] = entry


_register(
    ToolEntry(
        name="search_knowledge_base",
        description=(
            "Search the knowledge base for unstructured information: "
            "policies, menu descriptions, FAQ, room specs. "
            "Do NOT use for availability or booking state — use check_availability for those."
        ),
        input_schema=SearchKnowledgeBaseInput,
        output_schema=SearchKnowledgeBaseOutput,
        fn=search_knowledge_base,
    )
)

_register(
    ToolEntry(
        name="check_availability",
        description=(
            "Check available time slots for a resource type on a given date. "
            "Returns both exact matches and nearby suggestions."
        ),
        input_schema=CheckAvailabilityInput,
        output_schema=CheckAvailabilityOutput,
        fn=check_availability,
    )
)

_register(
    ToolEntry(
        name="get_resource_details",
        description="Get specs, pricing, and game titles for resources.",
        input_schema=GetResourceDetailsInput,
        output_schema=GetResourceDetailsOutput,
        fn=get_resource_details,
    )
)

_register(
    ToolEntry(
        name="create_booking",
        description=(
            "Create a new booking. Returns booking_id on success, "
            "or a structured conflict error if the slot is taken."
        ),
        input_schema=CreateBookingInput,
        output_schema=CreateBookingOutput,
        fn=create_booking,
    )
)

_register(
    ToolEntry(
        name="modify_booking",
        description="Adjust the start time or duration of an existing booking.",
        input_schema=ModifyBookingInput,
        output_schema=ModifyBookingOutput,
        fn=modify_booking,
    )
)

_register(
    ToolEntry(
        name="cancel_booking",
        description="Cancel an existing booking by booking_id.",
        input_schema=CancelBookingInput,
        output_schema=CancelBookingOutput,
        fn=cancel_booking,
    )
)


def get_tool(name: str) -> ToolEntry:
    """Look up a tool by name. Raises KeyError if not found."""
    return _REGISTRY[name]


def list_tools() -> list[str]:
    """Return the names of all registered tools."""
    return list(_REGISTRY.keys())


def all_tools() -> dict[str, ToolEntry]:
    """Return the full registry dict (name → ToolEntry)."""
    return dict(_REGISTRY)
