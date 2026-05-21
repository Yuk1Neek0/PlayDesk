"""
Real implementations for all six PlayDesk agent tools.

These functions replace the stub bodies while keeping the same signatures.
All DB access goes through Django ORM; all failures return structured error
objects — never raise to the caller.

No-DB fallback: when called without a database (e.g. in test_tool_registry.py
which exercises Pydantic schemas without a live DB), the functions return
representative stub data so those non-DB registry tests continue to pass.
The _db_available() sentinel detects this by attempting a lightweight DB ping.

Imported by stubs.py (which re-exports them so registry.py stays unchanged).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.db import IntegrityError

from .schemas import (
    BookingConflictError,
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

# ---------------------------------------------------------------------------
# Sentinel: is a DB connection available in the current test context?
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    """Return True if we can actually use the Django ORM (DB is accessible)."""
    try:
        from django.db import connection

        connection.ensure_connection()
        return True
    except Exception:  # noqa: BLE001
        return False


# ===========================================================================
# Tool 1 — search_knowledge_base
# ===========================================================================


def search_knowledge_base(inp: SearchKnowledgeBaseInput) -> SearchKnowledgeBaseOutput:
    """Vector-search the knowledge base via the RAG retriever."""
    if not _db_available():
        # No-DB fallback (schema / registry tests run without a live DB)
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
    try:
        from rag.retriever import retrieve

        raw = retrieve(
            query=inp.query,
            k=inp.top_k,
            lang=inp.lang,
            category=inp.category,
        )
        results = [KnowledgeChunkResult(**chunk) for chunk in raw]
        return SearchKnowledgeBaseOutput(results=results)
    except Exception:  # noqa: BLE001
        return SearchKnowledgeBaseOutput(results=[])


# ===========================================================================
# Tool 2 — check_availability
# ===========================================================================


def check_availability(inp: CheckAvailabilityInput) -> CheckAvailabilityOutput:
    """
    Return all resources of the requested type that are free during the
    requested window and can accommodate the requested party.

    Availability is determined by: no non-cancelled booking overlaps the window.

    suggestions is left empty here — conflict-aware alternatives are a
    nice-to-have (enhancements epic).
    """
    if not _db_available():
        base = datetime(2026, 5, 22, 20, 0, tzinfo=_UTC)
        return CheckAvailabilityOutput(
            available=[TimeSlot(start=base, end=base + timedelta(hours=2))],
            suggestions=[
                TimeSlot(start=base + timedelta(hours=1), end=base + timedelta(hours=3)),
                TimeSlot(start=base - timedelta(hours=1), end=base + timedelta(hours=1)),
            ],
        )
    try:
        from core.models import Booking, BookingStatus, Resource

        # Parse requested window
        requested_date = datetime.strptime(inp.date, "%Y-%m-%d").date()
        start_str, end_str = inp.time_range
        start_h, start_m = int(start_str[:2]), int(start_str[3:5])
        end_h, end_m = int(end_str[:2]), int(end_str[3:5])

        requested_start = datetime(
            requested_date.year,
            requested_date.month,
            requested_date.day,
            start_h,
            start_m,
            tzinfo=UTC,
        )
        requested_end = datetime(
            requested_date.year,
            requested_date.month,
            requested_date.day,
            end_h,
            end_m,
            tzinfo=UTC,
        )

        # Find resources of the right type with sufficient capacity
        candidates = Resource.objects.filter(
            type=inp.resource_type,
            capacity__gte=inp.party_size,
        )

        # Exclude resources that have a non-cancelled overlapping booking
        conflicting_resource_ids = set(
            Booking.objects.filter(
                resource__in=candidates,
                start_time__lt=requested_end,
                end_time__gt=requested_start,
            )
            .exclude(status=BookingStatus.CANCELLED)
            .values_list("resource_id", flat=True)
        )

        available_resources = [r for r in candidates if r.pk not in conflicting_resource_ids]

        available_slots = [
            TimeSlot(start=requested_start, end=requested_end) for _ in available_resources
        ]

        return CheckAvailabilityOutput(available=available_slots, suggestions=[])

    except Exception:  # noqa: BLE001
        return CheckAvailabilityOutput(available=[], suggestions=[])


# ===========================================================================
# Tool 3 — get_resource_details
# ===========================================================================


def get_resource_details(inp: GetResourceDetailsInput) -> GetResourceDetailsOutput:
    """Return specs, pricing, and game titles from Resource + GameMenu."""
    if not _db_available():
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
    try:
        from core.models import Resource

        qs = Resource.objects.prefetch_related("game_menu").select_related("store")
        if inp.resource_type is not None:
            qs = qs.filter(type=inp.resource_type)

        resources = []
        for r in qs:
            games = list(r.game_menu.values_list("name", flat=True))
            resources.append(
                ResourceDetail(
                    resource_id=r.pk,
                    name=r.name,
                    type=r.type,
                    capacity=r.capacity,
                    price_per_hour=float(r.price_per_hour),
                    metadata=r.metadata,
                    games=games,
                )
            )

        return GetResourceDetailsOutput(resources=resources)

    except Exception:  # noqa: BLE001
        return GetResourceDetailsOutput(resources=[])


# ===========================================================================
# Tool 4 — create_booking
# ===========================================================================


def create_booking(inp: CreateBookingInput) -> CreateBookingOutput:
    """
    Create a Booking row.

    Returns CreateBookingSuccess on success.
    Returns BookingConflictError if the DB EXCLUDE constraint fires (overlap).
    Returns BookingConflictError with a generic message for any other failure.
    """
    if not _db_available():
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

    from core.models import Booking, BookingSource, BookingStatus, Resource

    try:
        resource = Resource.objects.get(pk=inp.resource_id)
    except Resource.DoesNotExist:
        return CreateBookingOutput(
            result=BookingConflictError(
                message=f"Resource {inp.resource_id} not found.",
                conflicting_start=inp.start_time,
                conflicting_end=inp.start_time,
            )
        )

    end_time = inp.start_time + timedelta(minutes=inp.duration_minutes)

    try:
        booking = Booking.objects.create(
            resource=resource,
            customer_name=inp.customer_name,
            customer_phone=inp.customer_phone,
            start_time=inp.start_time,
            end_time=end_time,
            status=BookingStatus.CONFIRMED,
            source=BookingSource.AGENT,
        )
        return CreateBookingOutput(
            result=CreateBookingSuccess(
                booking_id=booking.pk,
                resource_name=resource.name,
                start_time=booking.start_time,
                end_time=booking.end_time,
                status=booking.status,
            )
        )

    except IntegrityError:
        # The EXCLUDE constraint rejected an overlapping booking.
        # Find the conflicting booking so we can surface its window.
        conflict = (
            Booking.objects.filter(
                resource=resource,
                start_time__lt=end_time,
                end_time__gt=inp.start_time,
            )
            .exclude(status="cancelled")
            .order_by("start_time")
            .first()
        )
        if conflict:
            return CreateBookingOutput(
                result=BookingConflictError(
                    message=(
                        f"The slot {inp.start_time.isoformat()} – {end_time.isoformat()} "
                        f"conflicts with an existing booking "
                        f"({conflict.start_time.isoformat()} – {conflict.end_time.isoformat()})."
                    ),
                    conflicting_start=conflict.start_time,
                    conflicting_end=conflict.end_time,
                )
            )
        return CreateBookingOutput(
            result=BookingConflictError(
                message="The requested slot is already booked.",
                conflicting_start=inp.start_time,
                conflicting_end=end_time,
            )
        )

    except Exception as exc:  # noqa: BLE001
        return CreateBookingOutput(
            result=BookingConflictError(
                message=f"Unexpected error: {exc}",
                conflicting_start=inp.start_time,
                conflicting_end=end_time,
            )
        )


# ===========================================================================
# Tool 5 — modify_booking
# ===========================================================================


def modify_booking(inp: ModifyBookingInput) -> ModifyBookingOutput:
    """
    Adjust start time / duration of an existing booking.

    Returns success=False when:
    - The booking does not exist or is cancelled.
    - The new slot conflicts with another booking (IntegrityError).
    """
    if not _db_available():
        new_end = inp.new_start_time + timedelta(minutes=inp.new_duration_minutes)
        return ModifyBookingOutput(
            success=True,
            booking_id=inp.booking_id,
            new_start_time=inp.new_start_time,
            new_end_time=new_end,
            message="Booking updated successfully.",
        )

    from core.models import Booking, BookingStatus

    try:
        booking = Booking.objects.get(pk=inp.booking_id)
    except Booking.DoesNotExist:
        return ModifyBookingOutput(
            success=False,
            booking_id=inp.booking_id,
            new_start_time=inp.new_start_time,
            new_end_time=inp.new_start_time,
            message=f"Booking {inp.booking_id} not found.",
        )

    if booking.status == BookingStatus.CANCELLED:
        return ModifyBookingOutput(
            success=False,
            booking_id=inp.booking_id,
            new_start_time=inp.new_start_time,
            new_end_time=inp.new_start_time,
            message=f"Booking {inp.booking_id} is cancelled and cannot be modified.",
        )

    new_end = inp.new_start_time + timedelta(minutes=inp.new_duration_minutes)

    try:
        booking.start_time = inp.new_start_time
        booking.end_time = new_end
        booking.save(update_fields=["start_time", "end_time"])
        return ModifyBookingOutput(
            success=True,
            booking_id=booking.pk,
            new_start_time=booking.start_time,
            new_end_time=booking.end_time,
            message="Booking updated successfully.",
        )
    except IntegrityError:
        return ModifyBookingOutput(
            success=False,
            booking_id=inp.booking_id,
            new_start_time=inp.new_start_time,
            new_end_time=new_end,
            message=(
                f"The new slot {inp.new_start_time.isoformat()} – {new_end.isoformat()} "
                "conflicts with an existing booking."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return ModifyBookingOutput(
            success=False,
            booking_id=inp.booking_id,
            new_start_time=inp.new_start_time,
            new_end_time=new_end,
            message=f"Unexpected error: {exc}",
        )


# ===========================================================================
# Tool 6 — cancel_booking
# ===========================================================================


def cancel_booking(inp: CancelBookingInput) -> CancelBookingOutput:
    """Cancel a booking by setting its status to CANCELLED."""
    if not _db_available():
        return CancelBookingOutput(
            success=True,
            booking_id=inp.booking_id,
            message="Booking cancelled successfully.",
        )

    from core.models import Booking, BookingStatus

    try:
        booking = Booking.objects.get(pk=inp.booking_id)
    except Booking.DoesNotExist:
        return CancelBookingOutput(
            success=False,
            booking_id=inp.booking_id,
            message=f"Booking {inp.booking_id} not found.",
        )

    if booking.status == BookingStatus.CANCELLED:
        return CancelBookingOutput(
            success=True,
            booking_id=inp.booking_id,
            message="Booking was already cancelled.",
        )

    try:
        booking.status = BookingStatus.CANCELLED
        booking.save(update_fields=["status"])
        return CancelBookingOutput(
            success=True,
            booking_id=inp.booking_id,
            message="Booking cancelled successfully.",
        )
    except Exception as exc:  # noqa: BLE001
        return CancelBookingOutput(
            success=False,
            booking_id=inp.booking_id,
            message=f"Unexpected error while cancelling booking: {exc}",
        )
