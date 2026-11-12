import hashlib
import re
from collections.abc import Mapping
from pathlib import Path

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
        user = environ.get("POSTGRES_USER", "elmify")
        password = environ.get("POSTGRES_PASSWORD", "elmify")
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
        name = environ.get("POSTGRES_DB", "elmify")
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


def per_checkout_test_database_name(environ: Mapping[str, str], checkout: Path) -> str | None:
    """Name the test database after this checkout, so worktrees never share one.

    Every worktree used to derive the same `test_elmify`, and two sessions
    running pytest at once dropped and recreated it under each other. An
    exported POSTGRES_DB still wins: None leaves Django's `test_<NAME>`
    default, so anyone exporting it sees exactly the old name. The basename
    keeps the name readable; the path digest keeps two clones that share a
    basename apart. Built from the path alone, so no git is needed. At most
    54 bytes, under Postgres's 63, leaving room for pytest-django's xdist
    `_gwN` suffix.
    """
    if environ.get("POSTGRES_DB"):
        return None
    resolved = checkout.resolve()
    slug = re.sub(r"[^a-z0-9]+", "_", resolved.name.lower()).strip("_")[:32]
    digest = hashlib.blake2s(str(resolved).encode(), digest_size=4).hexdigest()
    return "_".join(part for part in ("test_elmify", slug, digest) if part)
