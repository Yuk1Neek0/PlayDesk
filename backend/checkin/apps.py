"""Rotating in-store check-in (v11a rotating-checkin)."""

from django.apps import AppConfig


class CheckinConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "checkin"
