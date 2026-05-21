"""
Stub implementations for all six PlayDesk agent tools.

Each function accepts the typed Input schema and returns the typed Output schema.
No DB access — returns representative fake data.
Wave 1 replaces these bodies with real implementations; signatures are final.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .schemas import (
    CancelBookingInput,
    CancelBookingOutput,
    CheckAvailabilityInput,
    CheckAvailabilityOutput,
    CreateBookingInput,
    CreateBookingOutput,
    CreateBookingSuccess,
    GetResourceDetailsInput,
    GetResourceDetailsOutput,
    KnowledgeChunkResult,
    ModifyBookingInput,
    ModifyBookingOutput,
    ResourceDetail,
    SearchKnowledgeBaseInput,
    SearchKnowledgeBaseOutput,
    TimeSlot,
)

_UTC = UTC


def search_knowledge_base(inp: SearchKnowledgeBaseInput) -> SearchKnowledgeBaseOutput:
    """Vector-search the knowledge base. Stub returns one representative chunk."""
    return SearchKnowledgeBaseOutput(
        results=[
            KnowledgeChunkResult(
                chunk_id=1,
                content=(
                    "Outside food and beverages are not permitted in the gaming areas. "
                    "Drinks purchased at our counter are welcome."
                ),
                category="policy",
                source="house_rules.md",
                lang="en",
                score=0.92,
            )
        ]
    )


def check_availability(inp: CheckAvailabilityInput) -> CheckAvailabilityOutput:
    """Check resource availability. Stub returns one slot and one suggestion."""
    base = datetime(2026, 5, 22, 20, 0, tzinfo=_UTC)
    return CheckAvailabilityOutput(
        available=[
            TimeSlot(start=base, end=base + timedelta(hours=2)),
        ],
        suggestions=[
            TimeSlot(start=base + timedelta(hours=1), end=base + timedelta(hours=3)),
            TimeSlot(start=base - timedelta(hours=1), end=base + timedelta(hours=1)),
        ],
    )


def get_resource_details(inp: GetResourceDetailsInput) -> GetResourceDetailsOutput:
    """Return resource specs. Stub returns one PS5 console."""
    return GetResourceDetailsOutput(
        resources=[
            ResourceDetail(
                resource_id=1,
                name="PS5 Station 1",
                type="console",
                capacity=4,
                price_per_hour=60.0,
                metadata={"controllers": 4, "display": "55-inch 4K OLED"},
                games=["FIFA 25", "NBA 2K25", "Call of Duty: Black Ops 6"],
            )
        ]
    )


def create_booking(inp: CreateBookingInput) -> CreateBookingOutput:
    """Create a booking. Stub always succeeds with a fake booking_id."""
    start = inp.start_time
    end = start + timedelta(minutes=inp.duration_minutes)
    return CreateBookingOutput(
        result=CreateBookingSuccess(
            booking_id=1001,
            resource_name="PS5 Station 1",
            start_time=start,
            end_time=end,
            status="confirmed",
        )
    )


def modify_booking(inp: ModifyBookingInput) -> ModifyBookingOutput:
    """Modify a booking. Stub always reports success."""
    new_end = inp.new_start_time + timedelta(minutes=inp.new_duration_minutes)
    return ModifyBookingOutput(
        success=True,
        booking_id=inp.booking_id,
        new_start_time=inp.new_start_time,
        new_end_time=new_end,
        message="Booking updated successfully.",
    )


def cancel_booking(inp: CancelBookingInput) -> CancelBookingOutput:
    """Cancel a booking. Stub always reports success."""
    return CancelBookingOutput(
        success=True,
        booking_id=inp.booking_id,
        message="Booking cancelled successfully.",
    )
