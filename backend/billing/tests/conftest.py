"""Shared fixtures for the billing test suite."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest


@pytest.fixture()
def store(db):
    from core.models import Store

    return Store.objects.create(
        name="Billing Test Store",
        timezone="UTC",
        business_hours={},
        currency="USD",
    )


@pytest.fixture()
def resource(store):
    from core.models import Resource

    return Resource.objects.create(
        store=store,
        type="console",
        name="PS5 Station",
        capacity=4,
        price_per_hour=Decimal("40.00"),
        metadata={},
    )


@pytest.fixture()
def customer(store):
    from core.models import Customer

    return Customer.objects.create(
        store=store,
        phone="+12025551111",
        name="Test Customer",
        email="test@example.com",
    )


@pytest.fixture()
def booking(resource, customer):
    from core.models import Booking, BookingStatus

    return Booking.objects.create(
        resource=resource,
        customer=customer,
        customer_name=customer.name,
        customer_phone=customer.phone,
        start_time=datetime(2026, 7, 1, 14, 0, tzinfo=UTC),
        end_time=datetime(2026, 7, 1, 16, 0, tzinfo=UTC),
        status=BookingStatus.CONFIRMED,
    )
