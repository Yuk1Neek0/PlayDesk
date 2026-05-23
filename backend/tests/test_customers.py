"""Tests for the Customer model + resolve_customer helper + booking integration."""

from __future__ import annotations

import pytest

from core.customers import UnparseablePhoneError, resolve_customer


@pytest.fixture()
def store(db):
    from core.models import Store

    return Store.objects.create(
        name="Resolver Store", timezone="America/Toronto", business_hours={}
    )


@pytest.fixture()
def other_store(db):
    from core.models import Store

    return Store.objects.create(name="Other Store", timezone="UTC", business_hours={})


@pytest.fixture()
def resource(store):
    from core.models import Resource

    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5",
        capacity=4,
        price_per_hour="40.00",
        metadata={},
    )


# ---------------------------------------------------------------------------
# resolve_customer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_creates_customer_on_first_call(store):
    customer = resolve_customer(store=store, raw_phone="+1 (416) 555-0188", name="Alice")
    assert customer.pk is not None
    assert customer.phone == "+14165550188"
    assert customer.name == "Alice"
    assert customer.store_id == store.pk


@pytest.mark.django_db
def test_dedups_on_normalised_phone(store):
    """Different surface forms of the same phone must resolve to one row."""
    c1 = resolve_customer(store=store, raw_phone="+1 (416) 555-0188", name="Alice")
    c2 = resolve_customer(store=store, raw_phone="4165550188", name="Alice")
    c3 = resolve_customer(store=store, raw_phone="+14165550188", name="")
    assert c1.pk == c2.pk == c3.pk


@pytest.mark.django_db
def test_fills_blank_name_on_existing_customer(store):
    """A second booking with a name fills in a previously-blank customer name."""
    first = resolve_customer(store=store, raw_phone="+14165550188", name="")
    assert first.name == ""
    second = resolve_customer(store=store, raw_phone="+14165550188", name="Alice")
    assert second.pk == first.pk
    second.refresh_from_db()
    assert second.name == "Alice"


@pytest.mark.django_db
def test_does_not_overwrite_existing_name(store):
    """A second booking with a different name does NOT overwrite the existing one."""
    first = resolve_customer(store=store, raw_phone="+14165550188", name="Alice")
    second = resolve_customer(store=store, raw_phone="+14165550188", name="Imposter")
    assert second.pk == first.pk
    second.refresh_from_db()
    assert second.name == "Alice"


@pytest.mark.django_db
def test_per_store_isolation(store, other_store):
    """Same phone in two different stores yields two distinct customers."""
    c1 = resolve_customer(store=store, raw_phone="+14165550188", name="Alice")
    c2 = resolve_customer(store=other_store, raw_phone="+14165550188", name="Alice")
    assert c1.pk != c2.pk
    assert c1.store_id == store.pk
    assert c2.store_id == other_store.pk


@pytest.mark.django_db
def test_raises_on_unparseable_phone(store):
    with pytest.raises(UnparseablePhoneError):
        resolve_customer(store=store, raw_phone="garbage", name="Alice")


@pytest.mark.django_db
def test_locale_pref_can_be_upgraded_from_default(store):
    """A 中文 booking after an EN one shifts locale_pref — never the reverse."""
    first = resolve_customer(store=store, raw_phone="+14165550188", name="Alice")
    assert first.locale_pref == "en"
    resolve_customer(store=store, raw_phone="+14165550188", name="Alice", locale_pref="zh")
    first.refresh_from_db()
    assert first.locale_pref == "zh"


# ---------------------------------------------------------------------------
# Agent tool + REST integration
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_agent_create_booking_links_customer(resource):
    """create_booking via the agent tool links the new booking to a Customer."""
    from datetime import UTC, datetime

    from agent_tools.schemas import CreateBookingInput, CreateBookingSuccess
    from agent_tools.tools import create_booking
    from core.models import Booking

    out = create_booking(
        CreateBookingInput(
            resource_id=resource.pk,
            start_time=datetime(2026, 8, 1, 20, 0, tzinfo=UTC),
            duration_minutes=120,
            customer_name="Alice",
            customer_phone="(416) 555-0188",
        )
    )
    assert isinstance(out.result, CreateBookingSuccess)

    booking = Booking.objects.get(pk=out.result.booking_id)
    assert booking.customer is not None
    assert booking.customer.phone == "+14165550188"
    assert booking.customer.name == "Alice"


@pytest.mark.django_db(transaction=True)
def test_agent_create_booking_rejects_unparseable_phone(resource):
    """A garbage phone yields a structured BookingConflictError, not a crash."""
    from datetime import UTC, datetime

    from agent_tools.schemas import BookingConflictError, CreateBookingInput
    from agent_tools.tools import create_booking

    out = create_booking(
        CreateBookingInput(
            resource_id=resource.pk,
            start_time=datetime(2026, 8, 2, 20, 0, tzinfo=UTC),
            duration_minutes=60,
            customer_name="Alice",
            customer_phone="garbage",
        )
    )
    assert isinstance(out.result, BookingConflictError)
    assert "parse" in out.result.message.lower() or "phone" in out.result.message.lower()


@pytest.mark.django_db(transaction=True)
def test_rest_booking_create_links_customer(resource, client):
    """REST POST /api/bookings/ resolves a Customer end to end."""
    from datetime import UTC, datetime

    from core.models import Booking

    payload = {
        "resource_id": resource.pk,
        "customer_name": "Alice",
        "customer_phone": "+1 416 555 0188",
        "start_time": datetime(2026, 9, 1, 18, 0, tzinfo=UTC).isoformat(),
        "end_time": datetime(2026, 9, 1, 19, 0, tzinfo=UTC).isoformat(),
        "source": "manual",
    }
    resp = client.post("/api/bookings/", payload, content_type="application/json")
    assert resp.status_code == 201, resp.content

    booking_id = resp.json()["id"]
    booking = Booking.objects.get(pk=booking_id)
    assert booking.customer is not None
    assert booking.customer.phone == "+14165550188"


@pytest.mark.django_db(transaction=True)
def test_rest_booking_create_rejects_unparseable_phone(resource, client):
    """REST POST with a garbage phone returns 400 with a per-field error."""
    from datetime import UTC, datetime

    payload = {
        "resource_id": resource.pk,
        "customer_name": "Alice",
        "customer_phone": "garbage",
        "start_time": datetime(2026, 9, 2, 18, 0, tzinfo=UTC).isoformat(),
        "end_time": datetime(2026, 9, 2, 19, 0, tzinfo=UTC).isoformat(),
        "source": "manual",
    }
    resp = client.post("/api/bookings/", payload, content_type="application/json")
    assert resp.status_code == 400, resp.content
    assert "customer_phone" in resp.json()


# ---------------------------------------------------------------------------
# Backfill migration
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_backfill_links_existing_bookings_idempotently(resource):
    """Running the backfill twice does not duplicate Customers."""
    from datetime import UTC, datetime

    from core.models import Booking, BookingSource, BookingStatus, Customer

    # Insert a legacy-shape booking (no customer FK).
    booking = Booking.objects.create(
        resource=resource,
        customer_name="Legacy Alice",
        customer_phone="(416) 555-0199",
        start_time=datetime(2026, 10, 1, 20, 0, tzinfo=UTC),
        end_time=datetime(2026, 10, 1, 22, 0, tzinfo=UTC),
        status=BookingStatus.CONFIRMED,
        source=BookingSource.MANUAL,
    )
    # The agent-tool path auto-links new bookings now, so simulate "legacy
    # row" by unlinking after the signal fires.
    Booking.objects.filter(pk=booking.pk).update(customer=None, customer_phone="(416) 555-0199")

    from importlib import import_module

    from django.apps import apps as django_apps

    mig = import_module("core.migrations.0005_backfill_booking_customer")

    class _StubApps:
        def get_model(self, app_label, model_name):
            return django_apps.get_model(app_label, model_name)

    mig.backfill_customers(_StubApps(), None)
    mig.backfill_customers(_StubApps(), None)  # idempotency

    booking.refresh_from_db()
    assert booking.customer is not None
    assert booking.customer.phone == "+14165550199"

    # Exactly one customer with that phone.
    assert Customer.objects.filter(phone="+14165550199").count() == 1
