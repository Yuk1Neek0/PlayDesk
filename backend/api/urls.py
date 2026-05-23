"""
URL routing for the PlayDesk REST API app.

Wire into the project root with:
    path("api/", include("api.urls"))

All patterns here are relative to the "api/" prefix, so
    resources/        → GET /api/resources/
    bookings/         → GET POST /api/bookings/
    ...
"""

from django.urls import path

from .views import (
    AdminBookingListView,
    AdminConversationListView,
    AdminCustomerDetailView,
    AdminCustomerListView,
    AdminCustomerNoteCreateView,
    BookingDetailView,
    BookingListCreateView,
    ConversationCreateView,
    ConversationDetailView,
    QRActionDetailView,
    QRActionListCreateView,
    QRAnalyticsView,
    QREventCreateView,
    QRPublicView,
    ResourceAvailabilityView,
    ResourceDetailView,
    ResourceListView,
    stripe_webhook,
)

app_name = "api"

urlpatterns = [
    # Resources
    path("resources/", ResourceListView.as_view(), name="resource-list"),
    path("resources/<int:pk>/", ResourceDetailView.as_view(), name="resource-detail"),
    path(
        "resources/<int:pk>/availability/",
        ResourceAvailabilityView.as_view(),
        name="resource-availability",
    ),
    # Bookings
    path("bookings/", BookingListCreateView.as_view(), name="booking-list"),
    path("bookings/<int:pk>/", BookingDetailView.as_view(), name="booking-detail"),
    # Conversations
    path("conversations/", ConversationCreateView.as_view(), name="conversation-create"),
    path(
        "conversations/<int:pk>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    # Admin
    path(
        "admin/conversations/",
        AdminConversationListView.as_view(),
        name="admin-conversation-list",
    ),
    path(
        "admin/bookings/",
        AdminBookingListView.as_view(),
        name="admin-booking-list",
    ),
    path(
        "admin/customers/",
        AdminCustomerListView.as_view(),
        name="admin-customer-list",
    ),
    path(
        "admin/customers/<int:pk>/",
        AdminCustomerDetailView.as_view(),
        name="admin-customer-detail",
    ),
    path(
        "admin/customers/<int:pk>/notes/",
        AdminCustomerNoteCreateView.as_view(),
        name="admin-customer-note-create",
    ),
    # QR — One QR engagement
    path(
        "admin/qr-actions/",
        QRActionListCreateView.as_view(),
        name="admin-qr-action-list",
    ),
    path(
        "admin/qr-actions/<int:pk>/",
        QRActionDetailView.as_view(),
        name="admin-qr-action-detail",
    ),
    path(
        "admin/qr-analytics/",
        QRAnalyticsView.as_view(),
        name="admin-qr-analytics",
    ),
    path("qr/event/", QREventCreateView.as_view(), name="qr-event"),
    path("qr/<slug:slug>/", QRPublicView.as_view(), name="qr-public"),
    # Stripe webhook — confirms a booking when its deposit is paid
    path("webhooks/stripe/", stripe_webhook, name="stripe-webhook"),
]
