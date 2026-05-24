"""Billing app URL patterns. Wired into config/urls.py under /api/."""

from django.urls import path

from .views import (
    BookingCancelRefundView,
    ChargeBalanceView,
    PaymentLedgerView,
    PaymentStatusView,
    StripeAccountStatusView,
    StripeConnectView,
    StripeReturnView,
    StripeSettingsUpdateView,
    stripe_webhook,
)

app_name = "billing"

urlpatterns = [
    # Stripe Connect onboarding
    path("admin/stripe/connect/", StripeConnectView.as_view(), name="stripe-connect"),
    path("admin/stripe/return/", StripeReturnView.as_view(), name="stripe-return"),
    path("admin/stripe/status/", StripeAccountStatusView.as_view(), name="stripe-status"),
    path(
        "admin/stripe/settings/",
        StripeSettingsUpdateView.as_view(),
        name="stripe-settings",
    ),
    # Webhook receiver (v9 path; legacy /api/webhooks/stripe/ stays via api app)
    path("stripe/webhook/", stripe_webhook, name="stripe-webhook"),
    # Booking-scoped payment ops
    path(
        "admin/bookings/<int:pk>/charge-balance/",
        ChargeBalanceView.as_view(),
        name="charge-balance",
    ),
    path(
        "admin/bookings/<int:pk>/cancel/",
        BookingCancelRefundView.as_view(),
        name="booking-cancel",
    ),
    path(
        "bookings/<int:pk>/payment-status/",
        PaymentStatusView.as_view(),
        name="payment-status",
    ),
    path("admin/payments/", PaymentLedgerView.as_view(), name="payment-list"),
]
