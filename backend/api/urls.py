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
    BookingDetailView,
    BookingListCreateView,
    ConversationCreateView,
    ConversationDetailView,
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
    # Stripe webhook — confirms a booking when its deposit is paid
    path("webhooks/stripe/", stripe_webhook, name="stripe-webhook"),
]
