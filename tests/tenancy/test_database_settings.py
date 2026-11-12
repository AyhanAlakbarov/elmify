from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured


def database_config(
    environ: dict[str, str], *, require_explicit_role: bool
) -> dict[str, dict[str, object]]:
    from config.settings.database import database_config as build_database_config

    return build_database_config(environ, require_explicit_role=require_explicit_role)


def test_docker_targets_inherit_production_settings() -> None:
    dockerfile = (Path(__file__).parents[2] / "Dockerfile").read_text(encoding="utf-8")
    runtime_stage = dockerfile.split(" AS runtime\n", 1)[1].split("\nFROM ", 1)[0]

    assert "ENV DJANGO_SETTINGS_MODULE=config.settings.production" in runtime_stage.splitlines()
    assert "FROM runtime AS web" in dockerfile.splitlines()
    assert "FROM runtime AS worker" in dockerfile.splitlines()


def test_a_removed_role_name_is_refused_not_silently_accepted() -> None:
    """`runtime` is gone. A task definition still carrying it must fail at boot
    rather than connect as something -- the whole point of the split is that
    which role you are is now load-bearing."""
    with pytest.raises(ImproperlyConfigured):
        database_config(
            {"DATABASE_ROLE": "runtime", "POSTGRES_DB": "d", "POSTGRES_HOST": "h"},
            require_explicit_role=True,
        )


@pytest.mark.parametrize(
    "role,user_var",
    [
        ("runtime_engine", "POSTGRES_ENGINE_USER"),
        ("runtime_web", "POSTGRES_WEB_USER"),
    ],
)
def test_each_new_role_reads_its_own_credential_pair(role: str, user_var: str) -> None:
    cfg = database_config(
        {
            "DATABASE_ROLE": role,
            user_var: "u",
            user_var.replace("_USER", "_PASSWORD"): "p",
            "POSTGRES_DB": "d",
            "POSTGRES_HOST": "h",
        },
        require_explicit_role=True,
    )
    assert cfg["default"]["USER"] == "u"


@pytest.mark.parametrize(
    ("role", "user_var", "password_var", "user", "password"),
    [
        ("runtime_engine", "POSTGRES_ENGINE_USER", "POSTGRES_ENGINE_PASSWORD",
         "engine-user", "engine-password"),
        ("runtime_web", "POSTGRES_WEB_USER", "POSTGRES_WEB_PASSWORD",
         "web-user", "web-password"),
        ("migration", "POSTGRES_MIGRATION_USER", "POSTGRES_MIGRATION_PASSWORD",
         "migration-user", "migration-password"),
    ],
)
def test_selects_role_specific_credentials(
    role: str, user_var: str, password_var: str, user: str, password: str
) -> None:
    environ = {
        "DATABASE_ROLE": role,
        "POSTGRES_DB": "role-db",
        "POSTGRES_HOST": "role-host",
        "POSTGRES_PORT": "5544",
        "POSTGRES_USER": "generic-user",
        "POSTGRES_PASSWORD": "generic-password",
        user_var: user,
        password_var: password,
    }

    assert database_config(environ, require_explicit_role=True) == {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "role-db",
            "USER": user,
            "PASSWORD": password,
            "HOST": "role-host",
            "PORT": "5544",
        }
    }


def test_uses_generic_credentials_locally_when_role_is_absent() -> None:
    environ = {
        "POSTGRES_DB": "local-db",
        "POSTGRES_HOST": "local-host",
        "POSTGRES_PORT": "5544",
        "POSTGRES_USER": "generic-user",
        "POSTGRES_PASSWORD": "generic-password",
    }

    assert database_config(environ, require_explicit_role=False) == {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "local-db",
            "USER": "generic-user",
            "PASSWORD": "generic-password",
            "HOST": "local-host",
            "PORT": "5544",
        }
    }


def test_uses_role_credentials_locally_when_role_is_present() -> None:
    environ = {
        "DATABASE_ROLE": "runtime_engine",
        "POSTGRES_DB": "local-db",
        "POSTGRES_HOST": "local-host",
        "POSTGRES_USER": "generic-user",
        "POSTGRES_PASSWORD": "generic-password",
        "POSTGRES_ENGINE_USER": "engine-user",
        "POSTGRES_ENGINE_PASSWORD": "engine-password",
    }

    database = database_config(environ, require_explicit_role=False)["default"]

    assert database["USER"] == "engine-user"
    assert database["PASSWORD"] == "engine-password"


@pytest.mark.parametrize(
    "environ",
    [
        {
            "POSTGRES_DB": "role-db",
            "POSTGRES_HOST": "role-host",
            "POSTGRES_ENGINE_USER": "engine-user",
            "POSTGRES_ENGINE_PASSWORD": "engine-password",
        },
        {
            "DATABASE_ROLE": "owner",
            "POSTGRES_DB": "role-db",
            "POSTGRES_HOST": "role-host",
            "POSTGRES_ENGINE_USER": "engine-user",
            "POSTGRES_ENGINE_PASSWORD": "engine-password",
        },
        {
            "DATABASE_ROLE": "runtime_engine",
            "POSTGRES_DB": "role-db",
            "POSTGRES_HOST": "role-host",
            "POSTGRES_ENGINE_USER": "engine-user",
        },
    ],
)
def test_production_rejects_missing_invalid_or_incomplete_role_configuration(
    environ: dict[str, str],
) -> None:
    with pytest.raises(ImproperlyConfigured):
        database_config(environ, require_explicit_role=True)


@pytest.mark.parametrize("missing_key", ["POSTGRES_DB", "POSTGRES_HOST"])
def test_production_requires_shared_database_configuration(missing_key: str) -> None:
    environ = {
        "DATABASE_ROLE": "runtime_engine",
        "POSTGRES_DB": "role-db",
        "POSTGRES_HOST": "role-host",
        "POSTGRES_ENGINE_USER": "engine-user",
        "POSTGRES_ENGINE_PASSWORD": "engine-password",
    }
    del environ[missing_key]

    with pytest.raises(ImproperlyConfigured):
        database_config(environ, require_explicit_role=True)


def test_each_checkout_gets_its_own_test_database_unless_postgres_db_is_set() -> None:
    """Parallel worktrees used to share `test_elmify` and wedge each other."""
    import os
    import re

    from django.conf import settings

    from config.settings.database import per_checkout_test_database_name as name_for

    long_worktree = Path("/w/.claude/worktrees/Agent-A405257507DB195B5" + "-x" * 40)
    names = [
        name_for({}, Path("/home/a/elmify")),
        name_for({}, Path("/home/b/elmify")),  # same basename, other clone
        name_for({}, long_worktree),
        name_for({}, Path("/---")),  # nothing survives sanitising
    ]

    assert len(set(names)) == len(names)
    for name in names:
        assert name is not None
        assert re.fullmatch(r"[a-z_][a-z0-9_]*", name), name
        assert len(name.encode()) <= 54, name
    assert names[0].startswith("test_elmify_elmify_")
    # An explicit POSTGRES_DB wins: Django falls back to test_<POSTGRES_DB>.
    assert name_for({"POSTGRES_DB": "elmify_mine"}, Path("/home/a/elmify")) is None
    # And the suite itself runs under the derivation, not a shared name.
    assert settings.DATABASES["default"]["TEST"]["NAME"] == name_for(
        os.environ, settings.BASE_DIR
    )
