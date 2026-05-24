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
from rest_framework.routers import DefaultRouter

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
from .views_admin_stores import AdminStoreListView
from .views_campaigns import (
    CampaignCancelView,
    CampaignDetailView,
    CampaignListCreateView,
    CampaignRunsListView,
    CampaignSendView,
    SegmentDetailView,
    SegmentListCreateView,
    SegmentPreviewView,
)
from .views_checkin import (
    AdminCheckInView,
    AdminUndoCheckInView,
    CheckInActionView,
    CheckInInfoView,
)
from .views_customer_auth import LogoutView, RequestCodeView, VerifyCodeView
from .views_me import (
    MeView,
    MyBookingCancelView,
    MyBookingRescheduleView,
    MyBookingsView,
    MyMembershipView,
    MyRedeemView,
)
from .views_memberships import (
    AdjustPointsView,
    MembershipView,
    QRTierBadgeView,
    RedeemView,
    RewardTierViewSet,
    RewardViewSet,
)
from .views_metrics import BusinessMetricsView
from .views_outbound import OutboundMessageListView
from .views_public import DefaultStoreView, StoreBrandView
from .webhooks_twilio import (
    twilio_sms_webhook,
    twilio_voice_status_callback,
    twilio_voice_webhook,
    twilio_whatsapp_webhook,
)

# DRF router for the rewards/tiers CRUD ViewSets.
_router = DefaultRouter()
_router.register(r"admin/rewards", RewardViewSet, basename="admin-reward")
_router.register(r"admin/tiers", RewardTierViewSet, basename="admin-tier")

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
    # Memberships — composite membership view + adjust-points + redeem
    path(
        "admin/customers/<int:pk>/membership/",
        MembershipView.as_view(),
        name="admin-customer-membership",
    ),
    path(
        "admin/customers/<int:pk>/adjust-points/",
        AdjustPointsView.as_view(),
        name="admin-customer-adjust-points",
    ),
    path(
        "admin/customers/<int:pk>/redeem/",
        RedeemView.as_view(),
        name="admin-customer-redeem",
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
    path("qr/tier/", QRTierBadgeView.as_view(), name="qr-tier-badge"),
    path("qr/<slug:slug>/", QRPublicView.as_view(), name="qr-public"),
    # Campaigns — segments
    path(
        "admin/segments/",
        SegmentListCreateView.as_view(),
        name="admin-segment-list",
    ),
    path(
        "admin/segments/<int:pk>/",
        SegmentDetailView.as_view(),
        name="admin-segment-detail",
    ),
    path(
        "admin/segments/<int:pk>/preview/",
        SegmentPreviewView.as_view(),
        name="admin-segment-preview",
    ),
    # Campaigns — campaigns
    path(
        "admin/campaigns/",
        CampaignListCreateView.as_view(),
        name="admin-campaign-list",
    ),
    path(
        "admin/campaigns/<int:pk>/",
        CampaignDetailView.as_view(),
        name="admin-campaign-detail",
    ),
    path(
        "admin/campaigns/<int:pk>/send/",
        CampaignSendView.as_view(),
        name="admin-campaign-send",
    ),
    path(
        "admin/campaigns/<int:pk>/cancel/",
        CampaignCancelView.as_view(),
        name="admin-campaign-cancel",
    ),
    path(
        "admin/campaigns/<int:pk>/runs/",
        CampaignRunsListView.as_view(),
        name="admin-campaign-runs",
    ),
    # Admin store switcher
    path(
        "admin/stores/",
        AdminStoreListView.as_view(),
        name="admin-store-list",
    ),
    # Outbound message log (admin)
    path(
        "admin/outbound/",
        OutboundMessageListView.as_view(),
        name="admin-outbound-list",
    ),
    # Public branding signal — consumed by SSR booking + QR pages
    path(
        "public/store-brand/",
        StoreBrandView.as_view(),
        name="public-store-brand",
    ),
    # Default-store slug — drives the `/` → `/s/<default>/book` redirect
    path(
        "public/default-store/",
        DefaultStoreView.as_view(),
        name="public-default-store",
    ),
    # Composite business-metrics endpoint backing the /admin dashboard strip
    path(
        "admin/metrics/business/",
        BusinessMetricsView.as_view(),
        name="admin-business-metrics",
    ),
    # Customer-portal auth (v7) — phone+OTP gate for /s/[slug]/account
    path(
        "customer-auth/request-code/",
        RequestCodeView.as_view(),
        name="customer-auth-request-code",
    ),
    path(
        "customer-auth/verify-code/",
        VerifyCodeView.as_view(),
        name="customer-auth-verify-code",
    ),
    path(
        "customer-auth/logout/",
        LogoutView.as_view(),
        name="customer-auth-logout",
    ),
    # Customer-portal /api/me/* — gated on request.customer via middleware.
    path("me/", MeView.as_view(), name="me-profile"),
    path("me/bookings/", MyBookingsView.as_view(), name="me-bookings"),
    path(
        "me/bookings/<int:pk>/reschedule/",
        MyBookingRescheduleView.as_view(),
        name="me-booking-reschedule",
    ),
    path(
        "me/bookings/<int:pk>/cancel/",
        MyBookingCancelView.as_view(),
        name="me-booking-cancel",
    ),
    path("me/membership/", MyMembershipView.as_view(), name="me-membership"),
    path("me/redeem/", MyRedeemView.as_view(), name="me-redeem"),
    # Stripe webhook — confirms a booking when its deposit is paid
    path("webhooks/stripe/", stripe_webhook, name="stripe-webhook"),
    # Twilio SMS webhook — wires SMS into the agent loop
    path("webhooks/twilio/sms/", twilio_sms_webhook, name="twilio-sms-webhook"),
    # Twilio WhatsApp webhook — wires WhatsApp into the agent loop
    path(
        "webhooks/twilio/whatsapp/",
        twilio_whatsapp_webhook,
        name="twilio-whatsapp-webhook",
    ),
    # Twilio Voice webhook — v5 scaffold; static TwiML + phone Conversation row
    path("webhooks/twilio/voice/", twilio_voice_webhook, name="twilio-voice-webhook"),
    # Twilio Voice status callback — records missed/failed calls
    path(
        "webhooks/twilio/voice/status/",
        twilio_voice_status_callback,
        name="twilio-voice-status-callback",
    ),
    # v10b checkin — public per-booking check-in page + admin overrides.
    path("c/<str:token>/", CheckInInfoView.as_view(), name="checkin-info"),
    path(
        "c/<str:token>/check-in/",
        CheckInActionView.as_view(),
        name="checkin-action",
    ),
    path(
        "admin/bookings/<int:pk>/check-in/",
        AdminCheckInView.as_view(),
        name="admin-booking-checkin",
    ),
    path(
        "admin/bookings/<int:pk>/undo-check-in/",
        AdminUndoCheckInView.as_view(),
        name="admin-booking-undo-checkin",
    ),
]

# Rewards / tiers CRUD — DefaultRouter generates list+detail routes.
urlpatterns += _router.urls
