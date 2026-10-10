from django.apps import AppConfig


class DashboardConfig(AppConfig):
    """The student dashboard's logic: board, needs, the counsellor's view.

    No models. It exists apart from apps/portals because the board names the
    submitted state, which tests/portals/test_boundary.py keeps out of that app.
    """

    name = "apps.dashboard"
