"""PlayDesk URL configuration."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # REST API — resources, availability, booking CRUD, admin (api app)
    path("api/", include("api.urls")),
    # Agent — conversation creation + SSE streaming messages (agent app)
    path("api/", include("agent.urls")),
    # Pricing — public POST /api/quote/ + admin /api/admin/pricing-rules/
    path("api/", include("pricing.urls")),
    # Billing — Stripe Connect, webhook, charge-balance, refund (v9 epic)
    path("api/", include("billing.urls")),
    # Rotating-checkin — /api/c-in/* + /api/admin/checkin/* (v11a epic)
    path("api/", include("checkin.urls")),
]
