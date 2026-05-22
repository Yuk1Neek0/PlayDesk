"""
Tests for the real agent tool implementations (Issue #12).

All tests use pytest-django to get a real Postgres DB. Embedding calls
are intercepted by a FakeEmbeddingClient so no OpenAI API calls are made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import rag.embeddings as emb_module
from rag.embeddings import FakeEmbeddingClient

# ---------------------------------------------------------------------------
# Always use fake embeddings
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def use_fake_embeddings():
    emb_module.set_embedding_client(FakeEmbeddingClient())
    yield
    emb_module.reset_embedding_client()


# ---------------------------------------------------------------------------
# Shared DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(db):
    from core.models import Store

    return Store.objects.create(
        name="Test Store",
        timezone="UTC",
        business_hours={
            "mon": {"open": "10:00", "close": "23:00"},
            "tue": {"open": "10:00", "close": "23:00"},
            "wed": {"open": "10:00", "close": "23:00"},
            "thu": {"open": "10:00", "close": "23:00"},
            "fri": {"open": "10:00", "close": "23:00"},
            "sat": {"open": "10:00", "close": "23:00"},
            "sun": {"open": "10:00", "close": "23:00"},
        },
    )


@pytest.fixture()
def resource(store):
    from core.models import Resource

    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Station A",
        capacity=4,
        price_per_hour="58.00",
        metadata={"controllers": 2, "display": "65-inch 4K"},
    )


@pytest.fixture()
def game_menu(resource):
    from core.models import GameMenu

    GameMenu.objects.create(resource=resource, name="FIFA 25", platform="PS5", max_players=4)
    GameMenu.objects.create(resource=resource, name="Elden Ring", platform="PS5", max_players=2)
    return resource


@pytest.fixture()
def confirmed_booking(resource):
    from core.models import Booking, BookingSource, BookingStatus

    start = datetime(2026, 6, 1, 20, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    return Booking.objects.create(
        resource=resource,
        customer_name="Alice",
        customer_phone="111-1111",
        start_time=start,
        end_time=end,
        status=BookingStatus.CONFIRMED,
        source=BookingSource.MANUAL,
    )


# ---------------------------------------------------------------------------
# Tool 1 — search_knowledge_base
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSearchKnowledgeBase:
    def _seed_knowledge(self):
        from core.models import KnowledgeChunk
        from rag.embeddings import get_embedding_client

        client = get_embedding_client()
        chunks = [
            (
                "Outside food and beverages are not permitted.",
                "policies",
                "kb/policies.jsonl",
                "en",
            ),
            ("We open at 10 AM daily.", "business_hours", "kb/hours.jsonl", "en"),
        ]
        for content, cat, src, lang in chunks:
            KnowledgeChunk.objects.create(
                content=content,
                embedding=client.embed(content),
                category=cat,
                source=src,
                lang=lang,
            )

    def test_returns_results_from_db(self):
        from agent_tools.schemas import SearchKnowledgeBaseInput, SearchKnowledgeBaseOutput
        from agent_tools.tools import search_knowledge_base

        self._seed_knowledge()
        inp = SearchKnowledgeBaseInput(query="food policy", top_k=2)
        out = search_knowledge_base(inp)
        assert isinstance(out, SearchKnowledgeBaseOutput)
        assert len(out.results) >= 1

    def test_result_has_required_fields(self):
        from agent_tools.schemas import SearchKnowledgeBaseInput
        from agent_tools.tools import search_knowledge_base

        self._seed_knowledge()
        inp = SearchKnowledgeBaseInput(query="food", top_k=1)
        out = search_knowledge_base(inp)
        r = out.results[0]
        assert r.chunk_id > 0
        assert r.content
        assert r.category
        assert r.source
        assert r.lang
        assert 0.0 <= r.score <= 1.0

    def test_returns_empty_when_db_is_empty(self):
        from agent_tools.schemas import SearchKnowledgeBaseInput
        from agent_tools.tools import search_knowledge_base

        inp = SearchKnowledgeBaseInput(query="anything")
        out = search_knowledge_base(inp)
        assert out.results == []

    def test_lang_filter_is_forwarded(self):
        from agent_tools.schemas import SearchKnowledgeBaseInput
        from agent_tools.tools import search_knowledge_base
        from core.models import KnowledgeChunk
        from rag.embeddings import get_embedding_client

        client = get_embedding_client()
        KnowledgeChunk.objects.create(
            content="Chinese only chunk",
            embedding=client.embed("Chinese only chunk"),
            category="policies",
            source="kb/zh.jsonl",
            lang="zh",
        )
        KnowledgeChunk.objects.create(
            content="English only chunk",
            embedding=client.embed("English only chunk"),
            category="policies",
            source="kb/en.jsonl",
            lang="en",
        )

        inp = SearchKnowledgeBaseInput(query="chunk", top_k=5, lang="zh")
        out = search_knowledge_base(inp)
        assert all(r.lang == "zh" for r in out.results)


# ---------------------------------------------------------------------------
# Tool 2 — check_availability
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckAvailability:
    def test_returns_available_slot_when_resource_free(self, resource):
        from agent_tools.schemas import CheckAvailabilityInput
        from agent_tools.tools import check_availability

        inp = CheckAvailabilityInput(
            resource_type="console",
            date="2026-06-01",
            time_range=("10:00", "12:00"),
            party_size=2,
        )
        out = check_availability(inp)
        assert len(out.available) >= 1
        assert isinstance(out.suggestions, list)

    def test_not_available_when_booked(self, confirmed_booking):
        from agent_tools.schemas import CheckAvailabilityInput
        from agent_tools.tools import check_availability

        # The confirmed_booking occupies 20:00–22:00 on 2026-06-01
        inp = CheckAvailabilityInput(
            resource_type="console",
            date="2026-06-01",
            time_range=("20:00", "22:00"),
            party_size=1,
        )
        out = check_availability(inp)
        assert out.available == []

    def test_adjacent_slot_is_available(self, confirmed_booking):
        from agent_tools.schemas import CheckAvailabilityInput
        from agent_tools.tools import check_availability

        # 22:00–23:00 is adjacent (not overlapping) to 20:00–22:00
        inp = CheckAvailabilityInput(
            resource_type="console",
            date="2026-06-01",
            time_range=("22:00", "23:00"),
            party_size=1,
        )
        out = check_availability(inp)
        assert len(out.available) >= 1

    def test_party_size_too_large_returns_empty(self, resource):
        # resource capacity=4; party_size=10 should yield no matches
        from agent_tools.schemas import CheckAvailabilityInput
        from agent_tools.tools import check_availability

        inp = CheckAvailabilityInput(
            resource_type="console",
            date="2026-06-01",
            time_range=("10:00", "12:00"),
            party_size=10,
        )
        out = check_availability(inp)
        assert out.available == []

    def test_suggestions_are_always_a_list(self, resource):
        from agent_tools.schemas import CheckAvailabilityInput
        from agent_tools.tools import check_availability

        inp = CheckAvailabilityInput(
            resource_type="room",
            date="2026-06-01",
            time_range=("14:00", "16:00"),
            party_size=2,
        )
        out = check_availability(inp)
        assert isinstance(out.suggestions, list)

    def test_suggestions_offered_when_fully_booked(self, confirmed_booking):
        # The only console is booked 20:00–22:00; the same window has no
        # availability, so the tool should offer bookable alternatives.
        from agent_tools.schemas import CheckAvailabilityInput
        from agent_tools.tools import check_availability

        inp = CheckAvailabilityInput(
            resource_type="console",
            date="2026-06-01",
            time_range=("20:00", "22:00"),
            party_size=1,
        )
        out = check_availability(inp)
        assert out.available == []
        assert 1 <= len(out.suggestions) <= 2
        # Every suggested window must itself be free of the existing booking.
        booked_start = confirmed_booking.start_time
        booked_end = confirmed_booking.end_time
        for slot in out.suggestions:
            assert slot.end <= booked_start or slot.start >= booked_end

    def test_no_suggestions_when_requested_slot_is_free(self, resource):
        from agent_tools.schemas import CheckAvailabilityInput
        from agent_tools.tools import check_availability

        inp = CheckAvailabilityInput(
            resource_type="console",
            date="2026-06-01",
            time_range=("10:00", "12:00"),
            party_size=2,
        )
        out = check_availability(inp)
        assert len(out.available) >= 1
        assert out.suggestions == []


# ---------------------------------------------------------------------------
# Tool 3 — get_resource_details
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetResourceDetails:
    def test_returns_resource_data(self, game_menu):
        from agent_tools.schemas import GetResourceDetailsInput
        from agent_tools.tools import get_resource_details

        inp = GetResourceDetailsInput(resource_type="console")
        out = get_resource_details(inp)
        assert len(out.resources) == 1
        r = out.resources[0]
        assert r.name == "PS5 Station A"
        assert r.type == "console"
        assert r.capacity == 4
        assert r.price_per_hour == 58.0
        assert "FIFA 25" in r.games
        assert "Elden Ring" in r.games

    def test_no_type_filter_returns_all(self, game_menu):
        # Add a room resource
        from core.models import Resource

        Resource.objects.create(
            store=game_menu.store,
            type="room",
            name="VIP Room 1",
            capacity=8,
            price_per_hour="120.00",
        )

        from agent_tools.schemas import GetResourceDetailsInput
        from agent_tools.tools import get_resource_details

        inp = GetResourceDetailsInput(resource_type=None)
        out = get_resource_details(inp)
        types = {r.type for r in out.resources}
        assert "console" in types
        assert "room" in types

    def test_returns_empty_when_no_resources(self, db):
        from agent_tools.schemas import GetResourceDetailsInput
        from agent_tools.tools import get_resource_details

        inp = GetResourceDetailsInput(resource_type="room")
        out = get_resource_details(inp)
        assert out.resources == []


# ---------------------------------------------------------------------------
# Tool 4 — create_booking
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestCreateBooking:
    def test_creates_booking_successfully(self, resource):
        from agent_tools.schemas import CreateBookingInput, CreateBookingSuccess
        from agent_tools.tools import create_booking

        inp = CreateBookingInput(
            resource_id=resource.pk,
            start_time=datetime(2026, 6, 2, 14, 0, tzinfo=UTC),
            duration_minutes=120,
            customer_name="Bob",
            customer_phone="222-2222",
        )
        out = create_booking(inp)
        assert isinstance(out.result, CreateBookingSuccess)
        assert out.result.success is True
        assert out.result.booking_id is not None
        assert out.result.resource_name == resource.name

    def test_conflict_returns_structured_error(self, confirmed_booking, resource):
        from agent_tools.schemas import BookingConflictError
        from agent_tools.tools import create_booking

        # Try to book the same overlapping slot
        inp = create_booking.__wrapped__ if hasattr(create_booking, "__wrapped__") else None

        from agent_tools.schemas import CreateBookingInput

        inp = CreateBookingInput(
            resource_id=resource.pk,
            start_time=datetime(2026, 6, 1, 20, 0, tzinfo=UTC),
            duration_minutes=120,
            customer_name="Charlie",
            customer_phone="333-3333",
        )
        out = create_booking(inp)
        assert isinstance(out.result, BookingConflictError)
        assert out.result.error == "conflict"
        assert out.result.message

    def test_partial_overlap_also_conflicts(self, confirmed_booking, resource):
        from agent_tools.schemas import BookingConflictError, CreateBookingInput
        from agent_tools.tools import create_booking

        # 21:00–23:00 overlaps with 20:00–22:00
        inp = CreateBookingInput(
            resource_id=resource.pk,
            start_time=datetime(2026, 6, 1, 21, 0, tzinfo=UTC),
            duration_minutes=120,
            customer_name="Dave",
            customer_phone="444-4444",
        )
        out = create_booking(inp)
        assert isinstance(out.result, BookingConflictError)

    def test_nonexistent_resource_returns_error(self, db):
        from agent_tools.schemas import BookingConflictError, CreateBookingInput
        from agent_tools.tools import create_booking

        inp = CreateBookingInput(
            resource_id=99999,
            start_time=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
            duration_minutes=60,
            customer_name="Eve",
            customer_phone="555-5555",
        )
        out = create_booking(inp)
        assert isinstance(out.result, BookingConflictError)
        assert "not found" in out.result.message


# ---------------------------------------------------------------------------
# Tool 5 — modify_booking
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestModifyBooking:
    def test_modify_changes_time(self, confirmed_booking):
        from agent_tools.schemas import ModifyBookingInput
        from agent_tools.tools import modify_booking

        new_start = datetime(2026, 6, 1, 15, 0, tzinfo=UTC)
        inp = ModifyBookingInput(
            booking_id=confirmed_booking.pk,
            new_start_time=new_start,
            new_duration_minutes=90,
        )
        out = modify_booking(inp)
        assert out.success is True
        assert out.new_start_time == new_start
        assert out.new_end_time == new_start + timedelta(minutes=90)

    def test_modify_nonexistent_booking(self, db):
        from agent_tools.schemas import ModifyBookingInput
        from agent_tools.tools import modify_booking

        inp = ModifyBookingInput(
            booking_id=99999,
            new_start_time=datetime(2026, 6, 2, 10, 0, tzinfo=UTC),
            new_duration_minutes=60,
        )
        out = modify_booking(inp)
        assert out.success is False
        assert "not found" in out.message

    def test_modify_cancelled_booking_fails(self, confirmed_booking):
        from agent_tools.schemas import ModifyBookingInput
        from agent_tools.tools import modify_booking
        from core.models import BookingStatus

        confirmed_booking.status = BookingStatus.CANCELLED
        confirmed_booking.save()

        inp = ModifyBookingInput(
            booking_id=confirmed_booking.pk,
            new_start_time=datetime(2026, 6, 2, 10, 0, tzinfo=UTC),
            new_duration_minutes=60,
        )
        out = modify_booking(inp)
        assert out.success is False
        assert "cancelled" in out.message.lower()

    def test_modify_conflict_fails(self, resource):
        """Modifying booking A into a slot occupied by booking B must fail."""
        from agent_tools.schemas import ModifyBookingInput
        from agent_tools.tools import modify_booking
        from core.models import Booking, BookingSource, BookingStatus

        b1 = Booking.objects.create(
            resource=resource,
            customer_name="User1",
            customer_phone="100",
            start_time=datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 3, 12, 0, tzinfo=UTC),
            status=BookingStatus.CONFIRMED,
            source=BookingSource.MANUAL,
        )
        _b2 = Booking.objects.create(
            resource=resource,
            customer_name="User2",
            customer_phone="200",
            start_time=datetime(2026, 6, 3, 14, 0, tzinfo=UTC),
            end_time=datetime(2026, 6, 3, 16, 0, tzinfo=UTC),
            status=BookingStatus.CONFIRMED,
            source=BookingSource.MANUAL,
        )

        # Try to move b1 into b2's slot
        inp = ModifyBookingInput(
            booking_id=b1.pk,
            new_start_time=datetime(2026, 6, 3, 14, 0, tzinfo=UTC),
            new_duration_minutes=120,
        )
        out = modify_booking(inp)
        assert out.success is False


# ---------------------------------------------------------------------------
# Tool 6 — cancel_booking
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCancelBooking:
    def test_cancel_confirmed_booking(self, confirmed_booking):
        from agent_tools.schemas import CancelBookingInput
        from agent_tools.tools import cancel_booking
        from core.models import BookingStatus

        inp = CancelBookingInput(booking_id=confirmed_booking.pk)
        out = cancel_booking(inp)
        assert out.success is True
        assert out.booking_id == confirmed_booking.pk
        confirmed_booking.refresh_from_db()
        assert confirmed_booking.status == BookingStatus.CANCELLED

    def test_cancel_nonexistent_booking(self, db):
        from agent_tools.schemas import CancelBookingInput
        from agent_tools.tools import cancel_booking

        inp = CancelBookingInput(booking_id=99999)
        out = cancel_booking(inp)
        assert out.success is False
        assert "not found" in out.message

    def test_cancel_already_cancelled_returns_success(self, confirmed_booking):
        from agent_tools.schemas import CancelBookingInput
        from agent_tools.tools import cancel_booking
        from core.models import BookingStatus

        confirmed_booking.status = BookingStatus.CANCELLED
        confirmed_booking.save()

        inp = CancelBookingInput(booking_id=confirmed_booking.pk)
        out = cancel_booking(inp)
        assert out.success is True
        assert "already cancelled" in out.message
