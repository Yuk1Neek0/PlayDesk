from django.apps import AppConfig


class OutboundConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "outbound"

    def ready(self) -> None:
        # Wire booking-lifecycle signals that populate the outbound queue.
        from . import signals  # noqa: F401
