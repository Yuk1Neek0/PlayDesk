"""
Test URL configuration — includes api.urls under the 'api/' prefix
so that reverse() calls work in tests before config/urls.py is wired.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("api/", include("pricing.urls")),
]
