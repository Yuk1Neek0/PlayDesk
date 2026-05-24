"""URL patterns for v11a rotating-checkin.

Two prefixes, both wired in `config.urls`:

  - /api/c-in/...          public flow (no auth)
  - /api/admin/checkin/... staff-gated via StaffOnlyMiddleware
"""

from django.urls import path

from .views import CheckInView, LookupKeyView, RequestOtpView, VerifyAndFindView
from .views_admin import AdminActiveKeyView, AdminRotateNowView, AdminSettingsView

app_name = "checkin"

urlpatterns = [
    # Public
    path("c-in/lookup-key/", LookupKeyView.as_view(), name="lookup-key"),
    path("c-in/request-otp/", RequestOtpView.as_view(), name="request-otp"),
    path("c-in/verify-and-find/", VerifyAndFindView.as_view(), name="verify-and-find"),
    path("c-in/check-in/", CheckInView.as_view(), name="check-in"),
    # Admin
    path("admin/checkin/active-key/", AdminActiveKeyView.as_view(), name="admin-active-key"),
    path("admin/checkin/rotate/", AdminRotateNowView.as_view(), name="admin-rotate"),
    path("admin/checkin/settings/", AdminSettingsView.as_view(), name="admin-settings"),
]
