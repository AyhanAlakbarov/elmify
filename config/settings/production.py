import os

from .base import *  # noqa: F403
from .database import database_config

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
ALLOWED_HOSTS = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")
DATABASES = database_config(os.environ, require_explicit_role=True)

DEBUG = False
RESEARCH_QUEUE_URL = os.environ["RESEARCH_QUEUE_URL"]
EUROPASS_QUEUE_URL = os.environ["EUROPASS_QUEUE_URL"]
PORTAL_QUEUE_URL = os.environ["PORTAL_QUEUE_URL"]
DOCUMENT_QUEUE_URL = os.environ["DOCUMENT_QUEUE_URL"]
DOCUMENT_SCAN_QUEUE_URL = os.environ["DOCUMENT_SCAN_QUEUE_URL"]
MAILBOX_QUEUE_URL = os.environ["MAILBOX_QUEUE_URL"]
#: A shared counter is a production requirement (apps/ratelimit.py; CLAUDE.md /
#: owner rule "design for production: shared counters, multi-task"). Refuse to
#: start rather than silently fall back to base.py's LocMemCache, which would
#: make every rate limit and spend cap per-process again -- exactly the bug
#: this setting exists to close.
CACHE_URL = os.environ["CACHE_URL"]
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": CACHE_URL,
        "OPTIONS": {
            "socket_connect_timeout": CACHE_SOCKET_TIMEOUT_SECONDS,  # noqa: F405
            "socket_timeout": CACHE_SOCKET_TIMEOUT_SECONDS,  # noqa: F405
        },
    }
}
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
