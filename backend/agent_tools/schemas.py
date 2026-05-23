"""
Pydantic input/output schemas for all six PlayDesk agent tools.

These schemas are the contract between the agent loop and tool implementations.
Wave 1 swaps stub bodies for real DB-backed implementations without touching
the signatures or schema shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ===========================================================================
# Shared primitives
# ===========================================================================


class TimeSlot(BaseModel):
    """A single available (or suggested) time window.

    resource_id / resource_name identify which resource the window belongs to.
    They are optional so callers that don't tie a slot to a specific resource
    (e.g. a "nearby alternative" suggestion) can still emit a bare window.
    """

    start: datetime
    end: datetime
    resource_id: int | None = None
    resource_name: str | None = None


class BookingConflictError(BaseModel):
    """Structured conflict information returned by create_booking on failure."""

    error: Literal["conflict"] = "conflict"
    message: str
    conflicting_start: datetime
    conflicting_end: datetime


# ===========================================================================
# Tool 1 — search_knowledge_base
# ===========================================================================


class SearchKnowledgeBaseInput(BaseModel):
    query: str = Field(..., description="Natural-language query to search the knowledge base.")
    top_k: int = Field(5, ge=1, le=20, description="Number of chunks to return.")
    lang: str | None = Field(None, description="Filter by language code, e.g. 'en' or 'zh'.")
    category: str | None = Field(None, description="Filter by category (policy, faq, menu…).")


class KnowledgeChunkResult(BaseModel):
    chunk_id: int
    content: str
    category: str
    source: str
    lang: str
    score: float = Field(..., ge=0.0, le=1.0, description="Cosine similarity score.")


class SearchKnowledgeBaseOutput(BaseModel):
    results: list[KnowledgeChunkResult]


# ===========================================================================
# Tool 2 — check_availability
# ===========================================================================


class CheckAvailabilityInput(BaseModel):
    resource_type: Literal["console", "room", "table"] = Field(
        ..., description="Type of resource to check."
    )
    date: str = Field(..., description="Date in YYYY-MM-DD format.")
    time_range: tuple[str, str] = Field(
        ...,
        description="Requested start and end time as (HH:MM, HH:MM) in store local time.",
    )
    party_size: int = Field(..., ge=1, description="Number of people in the party.")


class CheckAvailabilityOutput(BaseModel):
    """
    available: list of exact slots matching the request.
    suggestions: nearby alternatives when available is empty.
    """

    available: list[TimeSlot]
    suggestions: list[TimeSlot]


# ===========================================================================
# Tool 3 — get_resource_details
# ===========================================================================


class GetResourceDetailsInput(BaseModel):
    resource_type: Literal["console", "room", "table"] | None = Field(
        None, description="Filter by type; omit to return all."
    )


class ResourceDetail(BaseModel):
    resource_id: int
    name: str
    type: str
    capacity: int
    price_per_hour: float
    metadata: dict[str, Any]
    games: list[str] = Field(default_factory=list, description="Game titles available.")


class GetResourceDetailsOutput(BaseModel):
    resources: list[ResourceDetail]


# ===========================================================================
# Tool 4 — create_booking
# ===========================================================================


class CreateBookingInput(BaseModel):
    resource_id: int
    start_time: datetime
    duration_minutes: int = Field(..., ge=30, description="Booking duration in minutes.")
    customer_name: str
    customer_phone: str


class CreateBookingSuccess(BaseModel):
    success: Literal[True] = True
    booking_id: int
    resource_name: str
    start_time: datetime
    end_time: datetime
    status: str


class CreateBookingOutput(BaseModel):
    """Union-style output: either a success or a structured conflict error."""

    result: CreateBookingSuccess | BookingConflictError


# ===========================================================================
# Tool 5 — modify_booking
# ===========================================================================


class ModifyBookingInput(BaseModel):
    booking_id: int
    new_start_time: datetime
    new_duration_minutes: int = Field(..., ge=30)


class ModifyBookingOutput(BaseModel):
    success: bool
    booking_id: int
    new_start_time: datetime
    new_end_time: datetime
    message: str


# ===========================================================================
# Tool 6 — cancel_booking
# ===========================================================================


class CancelBookingInput(BaseModel):
    booking_id: int


class CancelBookingOutput(BaseModel):
    success: bool
    booking_id: int
    message: str
