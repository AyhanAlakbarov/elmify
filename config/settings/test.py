from typing import Any, cast

from .base import *  # noqa: F403

SECRET_KEY = "test-only"  # nosec B105 - test fixture value, never deployed
ALLOWED_HOSTS = ["*"]
MIDDLEWARE = [  # noqa: F405
    middleware
    for middleware in MIDDLEWARE  # noqa: F405
    if middleware != "whitenoise.middleware.WhiteNoiseMiddleware"
]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# Forced explicitly, not left to base.py's "no CACHE_URL -> LocMemCache" fallback:
# a developer shell with CACHE_URL exported for other work (or for running
# tests/valkey/ by hand) would otherwise point the WHOLE suite at that real
# server, and the many autouse cache.clear() fixtures across the suite would
# FLUSHDB it -- wiping out whatever else is using that server, including a
# parallel test session. tests/valkey/test_rate_limited_valkey.py reads
# CACHE_URL itself and exercises the real backend directly; nothing else here
# should ever see it.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# View tests assert server behaviour -- MFA enforcement, tenant isolation,
# authorization, rate limiting, wizard sequencing -- through views that end in a
# render(). The real templates/ is rebuilt page by page (student dashboard plan);
# until a page exists, a stub here keeps its view tests off TemplateDoesNotExist.
# The stubs render nothing and pin no design; see tests/templates/README.md.
# Test settings only -- production never sees them.
# cast because base.py types TEMPLATES as list[dict[str, object]] -- mypy joins the
# heterogeneous values to object, so DIRS is not iterable to it.
cast(list[Any], TEMPLATES[0]["DIRS"]).append(BASE_DIR / "tests" / "templates")  # noqa: F405
