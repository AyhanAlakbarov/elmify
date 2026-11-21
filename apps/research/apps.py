from django.apps import AppConfig
from django.core import checks


def check_card_readers(**kwargs: object) -> list[checks.CheckMessage]:
    """A malformed CARD_READERS fails `manage.py check`, not the first model call."""
    from apps.research.card_engine.readers import StackMisconfigured, stack

    try:
        stack()
    except StackMisconfigured as error:
        return [checks.Error(str(error), id="research.E001")]
    return []


class ResearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.research"

    def ready(self) -> None:
        checks.register(check_card_readers)
