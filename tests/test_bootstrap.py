import re
from pathlib import Path

import django
import pytest
from django.conf import settings

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_contract() -> None:
    assert django.VERSION[:2] == (5, 2)
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert "django_multitenant" not in settings.INSTALLED_APPS


def test_every_declared_python_version_agrees() -> None:
    """The image's Python must match the one uv builds the venv for.

    Five files name a Python version and nothing made them agree, so a bump to
    one was invisible to the other four. That is not hypothetical: a base-image
    bump to python:3.14-slim landed while `requires-python` stayed ">=3.12,<3.13",
    uv built .venv/lib/python3.12 inside a 3.14 image, and the container could not
    import Django at all -- every stage, not just one. Nothing reported it,
    because until the portal-sandbox job existed CI never built an image, and
    the suite runs against the host's interpreter either way.

    Same shape as test_the_database_major_matches_the_postgres_the_tests_run_on
    in tests/infra/, and the same reason for existing: a version that drifts
    apart silently is worse than one that is wrong loudly.
    """
    read = lambda rel: (ROOT / rel).read_text()  # noqa: E731

    found = {
        "Dockerfile FROM": set(
            re.findall(r"^FROM python:(\d+\.\d+)-slim", read("Dockerfile"), re.M)
        ),
        "pyproject requires-python": set(
            re.findall(r'requires-python\s*=\s*">=(\d+\.\d+)', read("pyproject.toml"))
        ),
        "pyproject mypy python_version": set(
            re.findall(r'python_version\s*=\s*"(\d+\.\d+)"', read("pyproject.toml"))
        ),
        "ci.yml python-version": set(
            re.findall(r'python-version:\s*"(\d+\.\d+)"', read(".github/workflows/ci.yml"))
        ),
    }
    for name, versions in found.items():
        assert versions, f"no Python version found in {name} -- has the format changed?"

    ruff_target = set(re.findall(r'target-version\s*=\s*"py(\d)(\d+)"', read("pyproject.toml")))
    assert ruff_target, "no ruff target-version found -- has the format changed?"
    found["pyproject ruff target-version"] = {f"{a}.{b}" for a, b in ruff_target}

    agreed = set().union(*found.values())
    detail = {k: sorted(v) for k, v in found.items()}
    assert len(agreed) == 1, f"Python versions disagree: {detail}"


def test_the_ocr_image_runs_the_python_its_lock_was_resolved_for() -> None:
    """The OCR program is deliberately on another Python (its dependencies have no 3.14 wheels), and
    has the same failure mode on its own: ocr/uv.lock resolved for one interpreter, the image's
    base shipping another. Its two declarations must agree with each other."""
    dockerfile = (ROOT / "ocr/Dockerfile").read_text()
    pyproject = (ROOT / "ocr/pyproject.toml").read_text()
    base = re.findall(r"^FROM public\.ecr\.aws/lambda/python:(\d+\.\d+)@", dockerfile, re.M)
    pinned = re.findall(r'requires-python\s*=\s*"==(\d+\.\d+)\.\*"', pyproject)
    assert base and pinned, "no Python version found in ocr/ -- has the format changed?"
    assert set(base) == set(pinned), f"ocr/Dockerfile {base} vs ocr/pyproject.toml {pinned}"


def test_every_provider_key_defaults_to_empty() -> None:
    """A missing key must degrade to "this provider is off", never to a crash
    at import time on a developer machine."""
    from django.conf import settings

    for name in ("EXA_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY", "FIRECRAWL_API_KEY"):
        assert isinstance(getattr(settings, name), str)


def test_the_cache_backend_depends_on_cache_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """No CACHE_URL (a developer machine, the test suite) falls back to
    LocMemCache, so nothing needs a running cache server. CACHE_URL set (always
    true in production -- config/settings/production.py requires it) selects
    Django's RedisCache: a real, atomic INCR that keeps its own TTL, chosen
    over DatabaseCache (Django's SQL-backed cache), which was tried first and
    rejected on review -- its incr() is a non-atomic get-then-set that resets
    the key's expiry, so a rate limit's window stops holding under any
    concurrency (apps/ratelimit.py's docstring has the full story).

    Reloads config.settings.base directly, not django.conf.settings: this
    process's active settings module already captured base.py's names via
    `from .base import *` at import time, so mutating and reloading the base
    module here cannot change what the rest of the suite is running under.
    """
    import importlib

    from config.settings import base as base_settings

    try:
        monkeypatch.delenv("CACHE_URL", raising=False)
        importlib.reload(base_settings)
        assert base_settings.CACHES == {
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
        }

        monkeypatch.setenv("CACHE_URL", "redis://cache.example:6379/0")
        importlib.reload(base_settings)
        assert base_settings.CACHES == {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": "redis://cache.example:6379/0",
                "OPTIONS": {
                    "socket_connect_timeout": base_settings.CACHE_SOCKET_TIMEOUT_SECONDS,
                    "socket_timeout": base_settings.CACHE_SOCKET_TIMEOUT_SECONDS,
                },
            }
        }
    finally:
        monkeypatch.delenv("CACHE_URL", raising=False)
        importlib.reload(base_settings)
