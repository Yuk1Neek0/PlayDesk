"""Tests for billing.helpers — calc_deposit + calc_refund_amount."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from billing.helpers import (
    calc_deposit,
    calc_refund_amount,
    find_refund_pct,
    validate_refund_matrix,
)


@pytest.mark.django_db
class TestCalcDeposit:
    def test_mode_none_returns_zero(self, store, resource):
        store.deposit_mode = "none"
        store.deposit_value = Decimal("50.00")
        assert calc_deposit(store, resource, Decimal("80.00")) == Decimal("0.00")

    def test_percentage_mode(self, store, resource):
        store.deposit_mode = "percentage"
        store.deposit_value = Decimal("30")
        assert calc_deposit(store, resource, Decimal("80.00")) == Decimal("24.00")

    def test_fixed_mode(self, store, resource):
        store.deposit_mode = "fixed"
        store.deposit_value = Decimal("15.00")
        assert calc_deposit(store, resource, Decimal("80.00")) == Decimal("15.00")

    def test_capped_at_total(self, store, resource):
        store.deposit_mode = "fixed"
        store.deposit_value = Decimal("500.00")
        assert calc_deposit(store, resource, Decimal("80.00")) == Decimal("80.00")

    def test_resource_override_wins(self, store, resource):
        store.deposit_mode = "percentage"
        store.deposit_value = Decimal("30")
        resource.deposit_override_mode = "fixed"
        resource.deposit_override_value = Decimal("70.00")
        assert calc_deposit(store, resource, Decimal("80.00")) == Decimal("70.00")

    def test_zero_total_returns_zero(self, store, resource):
        store.deposit_mode = "percentage"
        store.deposit_value = Decimal("100")
        assert calc_deposit(store, resource, Decimal("0.00")) == Decimal("0.00")


class TestRefundMatrix:
    def test_find_pct_top_match(self):
        matrix = [
            {"min_hours": 48, "refund_pct": 100},
            {"min_hours": 24, "refund_pct": 50},
            {"min_hours": 0, "refund_pct": 0},
        ]
        assert find_refund_pct(matrix, 72.0) == 100

    def test_find_pct_mid_match(self):
        matrix = [
            {"min_hours": 48, "refund_pct": 100},
            {"min_hours": 24, "refund_pct": 50},
            {"min_hours": 0, "refund_pct": 0},
        ]
        assert find_refund_pct(matrix, 36.0) == 50

    def test_find_pct_below_lowest(self):
        matrix = [
            {"min_hours": 48, "refund_pct": 100},
            {"min_hours": 24, "refund_pct": 50},
        ]
        assert find_refund_pct(matrix, 1.0) == 0

    def test_handles_out_of_order_matrix(self):
        matrix = [
            {"min_hours": 0, "refund_pct": 0},
            {"min_hours": 48, "refund_pct": 100},
            {"min_hours": 24, "refund_pct": 50},
        ]
        assert find_refund_pct(matrix, 36.0) == 50

    def test_exact_boundary(self):
        matrix = [
            {"min_hours": 48, "refund_pct": 100},
            {"min_hours": 24, "refund_pct": 50},
        ]
        assert find_refund_pct(matrix, 48.0) == 100


@pytest.mark.django_db
class TestCalcRefundAmount:
    def _booking(self, resource, hours_ahead: float, deposit: Decimal):
        from core.models import Booking, BookingStatus, PaymentStatus

        start = datetime.now(tz=UTC) + timedelta(hours=hours_ahead)
        return Booking.objects.create(
            resource=resource,
            customer_name="x",
            customer_phone="+12025550000",
            start_time=start,
            end_time=start + timedelta(hours=1),
            status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.DEPOSIT_PAID,
            deposit_amount=deposit,
        )

    def test_full_refund_outside_window(self, store, resource):
        booking = self._booking(resource, hours_ahead=72, deposit=Decimal("24.00"))
        assert calc_refund_amount(store, booking) == Decimal("24.00")

    def test_partial_refund(self, store, resource):
        booking = self._booking(resource, hours_ahead=36, deposit=Decimal("24.00"))
        assert calc_refund_amount(store, booking) == Decimal("12.00")

    def test_no_refund_inside_window(self, store, resource):
        booking = self._booking(resource, hours_ahead=1, deposit=Decimal("24.00"))
        assert calc_refund_amount(store, booking) == Decimal("0.00")

    def test_zero_deposit_zero_refund(self, store, resource):
        booking = self._booking(resource, hours_ahead=72, deposit=Decimal("0.00"))
        assert calc_refund_amount(store, booking) == Decimal("0.00")


class TestValidateRefundMatrix:
    def test_happy_path(self):
        cleaned = validate_refund_matrix(
            [{"min_hours": 48, "refund_pct": 100}, {"min_hours": 0, "refund_pct": 0}]
        )
        assert cleaned[0]["min_hours"] == 48

    def test_rejects_non_list(self):
        with pytest.raises(ValueError):
            validate_refund_matrix({"min_hours": 48})

    def test_rejects_missing_field(self):
        with pytest.raises(ValueError):
            validate_refund_matrix([{"min_hours": 48}])

    def test_rejects_out_of_range_pct(self):
        with pytest.raises(ValueError):
            validate_refund_matrix([{"min_hours": 48, "refund_pct": 200}])
