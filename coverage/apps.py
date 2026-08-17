from django.apps import AppConfig


class CoverageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "coverage"

    def ready(self):
        from . import signals  # noqa: F401
