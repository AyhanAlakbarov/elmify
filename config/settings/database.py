from collections.abc import Mapping

from django.core.exceptions import ImproperlyConfigured

_ROLE_CREDENTIALS = {
    # `runtime` was one role doing two jobs: serving agencies and running the
    # engine. It is deliberately absent rather than aliased -- a task
    # definition still carrying it must fail at boot, because which role you
    # are is now the security boundary (2026-09-25 catalog-read-split design).
    "runtime_engine": ("POSTGRES_ENGINE_USER", "POSTGRES_ENGINE_PASSWORD"),
    "runtime_web": ("POSTGRES_WEB_USER", "POSTGRES_WEB_PASSWORD"),
    "migration": ("POSTGRES_MIGRATION_USER", "POSTGRES_MIGRATION_PASSWORD"),
}

_ROLE_ERROR = "DATABASE_ROLE must be runtime_engine, runtime_web, or migration"


def database_config(
    environ: Mapping[str, str], *, require_explicit_role: bool
) -> dict[str, dict[str, object]]:
    role = environ.get("DATABASE_ROLE")
    if role is None:
        if require_explicit_role:
            raise ImproperlyConfigured(_ROLE_ERROR)
        user = environ.get("POSTGRES_USER", "tehsil")
        password = environ.get("POSTGRES_PASSWORD", "tehsil")
    else:
        credential_names = _ROLE_CREDENTIALS.get(role)
        if credential_names is None:
            raise ImproperlyConfigured(_ROLE_ERROR)
        user_name, password_name = credential_names
        role_user = environ.get(user_name)
        role_password = environ.get(password_name)
        if not role_user or not role_password:
            raise ImproperlyConfigured(f"{role} database credentials are incomplete")
        user = role_user
        password = role_password

    if require_explicit_role:
        name = environ.get("POSTGRES_DB")
        host = environ.get("POSTGRES_HOST")
        if not name or not host:
            raise ImproperlyConfigured("POSTGRES_DB and POSTGRES_HOST are required")
    else:
        name = environ.get("POSTGRES_DB", "tehsil")
        host = environ.get("POSTGRES_HOST", "127.0.0.1")

    return {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": name,
            "USER": user,
            "PASSWORD": password,
            "HOST": host,
            "PORT": environ.get("POSTGRES_PORT", "5432"),
        }
    }
