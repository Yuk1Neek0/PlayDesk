"""
REST API tests for the PlayDesk DRF endpoints.

Covers happy paths and the concurrent-overlap 409 behaviour.

Run with:
    cd backend && pytest tests/test_api_rest.py -v

Requires a live Postgres database (same as the overlap constraint tests).
Tests use DRF's APIClient with the 'api' app's URLconf.
"""

from datetime import UTC, datetime

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.urls("tests.urls"),
]

_UTC = UTC


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_client():
    return APIClient()


@pytest.fixture()
def store(db):
    from core.models import Store

    return Store.objects.create(
        name="Pixel Lounge",
        timezone="UTC",
        business_hours={
            "mon": {"open": "10:00", "close": "22:00"},
            "tue": {"open": "10:00", "close": "22:00"},
            "wed": {"open": "10:00", "close": "22:00"},
            "thu": {"open": "10:00", "close": "22:00"},
            "fri": {"open": "10:00", "close": "23:00"},
            "sat": {"open": "10:00", "close": "23:00"},
            "sun": {"open": "11:00", "close": "21:00"},
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
        price_per_hour="60.00",
        metadata={"controller_count": 2, "has_vr": False},
    )


@pytest.fixture()
def resource2(store):
    from core.models import Resource

    return Resource.objects.create(
        store=store,
        type="room",
        name="Private Room 1",
        capacity=8,
        price_per_hour="150.00",
    )


def _dt(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# Resource endpoints
# ---------------------------------------------------------------------------


class TestResourceList:
    def test_list_returns_200(self, api_client, resource):
        url = reverse("api:resource-list")
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert "count" in data
        assert "results" in data
        assert data["count"] >= 1

    def test_filter_by_type(self, api_client, resource, resource2):
        url = reverse("api:resource-list")
        resp = api_client.get(url, {"type": "console"})
        assert resp.status_code == status.HTTP_200_OK
        results = resp.json()["results"]
        assert all(r["type"] == "console" for r in results)

    def test_filter_by_invalid_type_returns_400(self, api_client, resource):
        url = reverse("api:resource-list")
        resp = api_client.get(url, {"type": "spaceship"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_resource_fields(self, api_client, resource):
        url = reverse("api:resource-list")
        resp = api_client.get(url)
        item = resp.json()["results"][0]
        for field in ("id", "store_id", "type", "name", "capacity", "price_per_hour"):
            assert field in item, f"missing field: {field}"


class TestResourceDetail:
    def test_get_resource(self, api_client, resource):
        url = reverse("api:resource-detail", kwargs={"pk": resource.pk})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["id"] == resource.pk

    def test_404_for_missing(self, api_client):
        url = reverse("api:resource-detail", kwargs={"pk": 99999})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Availability endpoint
# ---------------------------------------------------------------------------


class TestResourceAvailability:
    def test_returns_full_day_when_no_bookings(self, api_client, resource):
        # Use a Monday (2026-06-01 is a Monday)
        url = reverse("api:resource-availability", kwargs={"pk": resource.pk})
        resp = api_client.get(url, {"date": "2026-06-01"})
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["resource_id"] == resource.pk
        assert data["date"] == "2026-06-01"
        assert len(data["available"]) == 1  # one contiguous free block
        assert "suggestions" in data

    def test_missing_date_returns_400(self, api_client, resource):
        url = reverse("api:resource-availability", kwargs={"pk": resource.pk})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_date_format_returns_400(self, api_client, resource):
        url = reverse("api:resource-availability", kwargs={"pk": resource.pk})
        resp = api_client.get(url, {"date": "01-06-2026"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_slot_subtracted_by_existing_booking(self, api_client, resource):
        from core.models import Booking

        # Book 14:00–16:00 on a Monday
        start = _dt(2026, 6, 1, 14)
        end = _dt(2026, 6, 1, 16)
        Booking.objects.create(
            resource=resource,
            customer_name="Alice",
            customer_phone="+14165550111",
            start_time=start,
            end_time=end,
            status="confirmed",
            source="manual",
        )

        url = reverse("api:resource-availability", kwargs={"pk": resource.pk})
        resp = api_client.get(url, {"date": "2026-06-01"})
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        # Should have two free windows: 10:00–14:00 and 16:00–22:00
        assert len(data["available"]) == 2

    def test_404_for_missing_resource(self, api_client):
        url = reverse("api:resource-availability", kwargs={"pk": 99999})
        resp = api_client.get(url, {"date": "2026-06-01"})
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Booking list / create
# ---------------------------------------------------------------------------


class TestBookingCreate:
    def _payload(self, resource, start_hour=20, end_hour=22):
        start = _dt(2026, 6, 2, start_hour)
        end = _dt(2026, 6, 2, end_hour)
        return {
            "resource_id": resource.pk,
            "customer_name": "Bob Smith",
            "customer_phone": "+86-138-0000-0001",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "source": "manual",
        }

    def test_create_booking_happy_path(self, api_client, resource):
        url = reverse("api:booking-list")
        resp = api_client.post(url, self._payload(resource), format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        for field in (
            "id",
            "resource_id",
            "customer_name",
            "start_time",
            "end_time",
            "status",
            "created_at",
        ):
            assert field in data, f"missing field: {field}"
        assert data["status"] == "pending"
        assert data["resource_id"] == resource.pk

    def test_missing_required_field_returns_400(self, api_client, resource):
        url = reverse("api:booking-list")
        payload = self._payload(resource)
        del payload["customer_name"]
        resp = api_client.post(url, payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_end_before_start_returns_400(self, api_client, resource):
        url = reverse("api:booking-list")
        payload = self._payload(resource, start_hour=22, end_hour=20)
        resp = api_client.post(url, payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_overlap_returns_409(self, api_client, resource):
        """Two identical slots for the same resource must yield one 201 and one 409."""
        url = reverse("api:booking-list")
        payload = self._payload(resource)

        resp1 = api_client.post(url, payload, format="json")
        assert resp1.status_code == status.HTTP_201_CREATED

        resp2 = api_client.post(url, payload, format="json")
        assert resp2.status_code == status.HTTP_409_CONFLICT
        data = resp2.json()
        assert "detail" in data

    def test_different_resources_same_slot_both_succeed(self, api_client, resource, resource2):
        """Overlap constraint is per-resource; different resources can share a time slot."""
        url = reverse("api:booking-list")
        payload1 = self._payload(resource)
        payload2 = self._payload(resource2)

        resp1 = api_client.post(url, payload1, format="json")
        resp2 = api_client.post(url, payload2, format="json")
        assert resp1.status_code == status.HTTP_201_CREATED
        assert resp2.status_code == status.HTTP_201_CREATED


class TestBookingList:
    def test_list_returns_200(self, api_client, resource):
        url = reverse("api:booking-list")
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert "results" in resp.json()

    def test_filter_by_status(self, api_client, resource):
        from core.models import Booking

        Booking.objects.create(
            resource=resource,
            customer_name="Test",
            customer_phone="+14165550100",
            start_time=_dt(2026, 7, 1, 10),
            end_time=_dt(2026, 7, 1, 12),
            status="confirmed",
            source="manual",
        )
        url = reverse("api:booking-list")
        resp = api_client.get(url, {"status": "confirmed"})
        assert resp.status_code == status.HTTP_200_OK
        results = resp.json()["results"]
        assert all(r["status"] == "confirmed" for r in results)

    def test_filter_by_date(self, api_client, resource):
        from core.models import Booking

        Booking.objects.create(
            resource=resource,
            customer_name="DateTest",
            customer_phone="+14165550100",
            start_time=_dt(2026, 8, 15, 14),
            end_time=_dt(2026, 8, 15, 16),
            status="pending",
            source="manual",
        )
        url = reverse("api:booking-list")
        resp = api_client.get(url, {"date": "2026-08-15"})
        assert resp.status_code == status.HTTP_200_OK
        results = resp.json()["results"]
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Booking detail: GET / PATCH / DELETE
# ---------------------------------------------------------------------------


@pytest.fixture()
def booking(resource):
    from core.models import Booking

    return Booking.objects.create(
        resource=resource,
        customer_name="Charlie",
        customer_phone="+14165550001",
        start_time=_dt(2026, 6, 5, 18),
        end_time=_dt(2026, 6, 5, 20),
        status="pending",
        source="manual",
    )


class TestBookingDetail:
    def test_get_booking(self, api_client, booking):
        url = reverse("api:booking-detail", kwargs={"pk": booking.pk})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["id"] == booking.pk

    def test_404_for_missing(self, api_client):
        url = reverse("api:booking-detail", kwargs={"pk": 99999})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_patch_status(self, api_client, booking):
        url = reverse("api:booking-detail", kwargs={"pk": booking.pk})
        resp = api_client.patch(url, {"status": "confirmed"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "confirmed"

    def test_patch_customer_name(self, api_client, booking):
        url = reverse("api:booking-detail", kwargs={"pk": booking.pk})
        resp = api_client.patch(url, {"customer_name": "Charlie Updated"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["customer_name"] == "Charlie Updated"

    def test_delete_booking(self, api_client, booking):
        url = reverse("api:booking-detail", kwargs={"pk": booking.pk})
        resp = api_client.delete(url)
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        # Confirm it's gone
        resp2 = api_client.get(url)
        assert resp2.status_code == status.HTTP_404_NOT_FOUND

    def test_patch_overlap_returns_409(self, api_client, resource, booking):
        """PATCH that moves booking time to overlap with an existing booking → 409."""
        from core.models import Booking

        # Create a second booking in a different slot
        other = Booking.objects.create(
            resource=resource,
            customer_name="Diana",
            customer_phone="+14165550002",
            start_time=_dt(2026, 6, 5, 14),
            end_time=_dt(2026, 6, 5, 16),
            status="confirmed",
            source="manual",
        )
        url = reverse("api:booking-detail", kwargs={"pk": other.pk})
        # Move other into overlap with booking (18–20)
        resp = api_client.patch(
            url,
            {
                "start_time": _dt(2026, 6, 5, 17).isoformat(),
                "end_time": _dt(2026, 6, 5, 19).isoformat(),
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


class TestConversations:
    def test_create_conversation(self, api_client):
        url = reverse("api:conversation-create")
        resp = api_client.post(url, {"customer_identifier": "browser-uuid-1234"}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["customer_identifier"] == "browser-uuid-1234"
        assert data["status"] == "active"

    def test_create_conversation_auto_identifier(self, api_client):
        url = reverse("api:conversation-create")
        resp = api_client.post(url, {}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        # Server generates a UUID
        assert resp.json()["customer_identifier"]

    def test_get_conversation_detail(self, api_client):
        url = reverse("api:conversation-create")
        resp = api_client.post(url, {"customer_identifier": "test-123"}, format="json")
        conv_id = resp.json()["id"]

        detail_url = reverse("api:conversation-detail", kwargs={"pk": conv_id})
        resp2 = api_client.get(detail_url)
        assert resp2.status_code == status.HTTP_200_OK
        data = resp2.json()
        assert data["id"] == conv_id
        assert "messages" in data

    def test_conversation_404(self, api_client):
        url = reverse("api:conversation-detail", kwargs={"pk": 99999})
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


class TestAdminConversations:
    def test_admin_list_conversations(self, api_client):
        from core.models import Conversation

        Conversation.objects.create(customer_identifier="admin-test-1", status="active")
        Conversation.objects.create(customer_identifier="admin-test-2", status="closed")

        url = reverse("api:admin-conversation-list")
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["count"] >= 2

    def test_admin_conversations_filter_by_status(self, api_client):
        from core.models import Conversation

        Conversation.objects.create(customer_identifier="active-one", status="active")
        Conversation.objects.create(customer_identifier="closed-one", status="closed")

        url = reverse("api:admin-conversation-list")
        resp = api_client.get(url, {"status": "active"})
        assert resp.status_code == status.HTTP_200_OK
        results = resp.json()["results"]
        assert all(r["status"] == "active" for r in results)

    def test_admin_conversations_newest_first(self, api_client):
        from core.models import Conversation

        c1 = Conversation.objects.create(customer_identifier="first")
        c2 = Conversation.objects.create(customer_identifier="second")

        url = reverse("api:admin-conversation-list")
        resp = api_client.get(url)
        ids = [r["id"] for r in resp.json()["results"]]
        # Newest (c2) should appear before c1
        assert ids.index(c2.pk) < ids.index(c1.pk)


class TestAdminBookings:
    def test_admin_list_bookings(self, api_client, resource):
        from core.models import Booking

        Booking.objects.create(
            resource=resource,
            customer_name="Admin Test",
            customer_phone="+14165550100",
            start_time=_dt(2026, 9, 1, 10),
            end_time=_dt(2026, 9, 1, 12),
            status="confirmed",
            source="manual",
        )

        url = reverse("api:admin-booking-list")
        resp = api_client.get(url)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["count"] >= 1

    def test_admin_bookings_newest_first(self, api_client, resource):
        from core.models import Booking

        b1 = Booking.objects.create(
            resource=resource,
            customer_name="First",
            customer_phone="+14165550100",
            start_time=_dt(2026, 9, 2, 10),
            end_time=_dt(2026, 9, 2, 11),
            status="pending",
            source="manual",
        )
        b2 = Booking.objects.create(
            resource=resource,
            customer_name="Second",
            customer_phone="+14165550101",
            start_time=_dt(2026, 9, 3, 10),
            end_time=_dt(2026, 9, 3, 11),
            status="pending",
            source="manual",
        )

        url = reverse("api:admin-booking-list")
        resp = api_client.get(url)
        ids = [r["id"] for r in resp.json()["results"]]
        # Newest (b2) should appear before b1
        assert ids.index(b2.pk) < ids.index(b1.pk)

    def test_admin_bookings_filter_by_status(self, api_client, resource):
        from core.models import Booking

        Booking.objects.create(
            resource=resource,
            customer_name="Pending",
            customer_phone="+14165550100",
            start_time=_dt(2026, 9, 4, 10),
            end_time=_dt(2026, 9, 4, 11),
            status="pending",
            source="manual",
        )

        url = reverse("api:admin-booking-list")
        resp = api_client.get(url, {"status": "pending"})
        assert resp.status_code == status.HTTP_200_OK
        results = resp.json()["results"]
        assert all(r["status"] == "pending" for r in results)
