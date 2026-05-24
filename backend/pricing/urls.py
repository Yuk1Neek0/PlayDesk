"""
URL routing for the pricing app.

Mounted at the project root via:
    path("api/", include("pricing.urls"))
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import PricingRuleViewSet, QuoteView

_router = DefaultRouter()
_router.register(r"admin/pricing-rules", PricingRuleViewSet, basename="admin-pricing-rule")

app_name = "pricing"

urlpatterns = [
    path("quote/", QuoteView.as_view(), name="quote"),
]

urlpatterns += _router.urls
