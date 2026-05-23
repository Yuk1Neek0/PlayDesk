from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        # Wire up booking counter signals (Customer.total_visits / last_visit_at).
        from . import signals  # noqa: F401
