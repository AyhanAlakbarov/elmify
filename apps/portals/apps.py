from django.apps import AppConfig


class PortalsConfig(AppConfig):
    name = "apps.portals"

    def ready(self) -> None:
        from django.contrib.auth.signals import user_logged_in

        from .pairing import remember_login

        user_logged_in.connect(remember_login, dispatch_uid="portals.remember_login")
