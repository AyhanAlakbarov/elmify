"""One fixed-window rate limiter, shared by every endpoint that needs one.

Backed by Django's ``CACHES["default"]``. In production
(config/settings/production.py) that is Redis/Valkey (``CACHE_URL``, required
-- the setting refuses to start without it): a real, atomic ``INCR`` that keeps
the key's TTL, which is why this backend was chosen over the two alternatives
tried first. LocMemCache (Django's default when ``CACHES`` is unset) is
per-process and resets on every deploy. Django's SQL-backed DatabaseCache was
tried next and rejected on review: its ``incr()`` is a non-atomic get-then-set
that resets the key's expiry to Django's 300s default, so a window stops
holding the moment two increments race or the key sits idle a few minutes --
silently weakening every limit while looking shared.

Fails closed: if the cache backend is unreachable, ``cache.add``/``cache.incr``
raise, and this function raises with them rather than falling back to
"allowed". A rate limit or a spend cap that cannot be checked must refuse, not
let the caller through unmetered.
"""

import hashlib
import time
import unicodedata
from uuid import UUID

from django.core.cache import cache


def rate_limited(bucket: str, actor_id: UUID | int, *, limit: int, window_seconds: int) -> bool:
    """True once ``actor_id`` has exceeded ``limit`` actions in ``bucket``."""
    # The window index is part of the key (N2, 2026-09-27 re-review): Django's
    # RedisCacheClient.incr checks EXISTS then runs INCR as two separate Redis
    # commands, and if the key expires between them, INCR recreates it at 1 with
    # NO expiry. A key with no window index would then be stuck forever -- every
    # later cache.add() (a SET NX) fails against the surviving key, so the actor
    # is locked out of this bucket permanently, not just for one window. With the
    # index, only the window that raced is stuck; the next window computes a
    # different key. The leaked, TTL-less key itself is not cleaned up -- it is
    # abandoned once its window passes, since nothing ever reads or writes that
    # exact key again. Accepted rather than closed: one stray key per race,
    # forever, is a bounded, rare cost; the alternative (an EXPIRE-after-INCR
    # round trip, or a Lua script combining SET NX EX + INCR + EXPIRE NX
    # atomically) is real work for a leak this small and this rare.
    window = int(time.time() // window_seconds)
    key = f"ratelimit:{bucket}:{actor_id}:{window}"
    cache.add(key, 0, timeout=window_seconds)
    try:
        count = cache.incr(key)
    except ValueError:
        # The key expired between add() and incr() -- a narrow race at the
        # window boundary (Redis's own INCR is atomic; this can only happen
        # between the two separate calls above). Treat this request as the
        # first of a fresh window rather than losing it.
        cache.add(key, 0, timeout=window_seconds)
        count = cache.incr(key)
    return bool(count > limit)


#: Ten sign-in attempts per username in fifteen minutes, shared by the JSON door
#: (apps/documents/api.py::auth_login) and the HTML door (accounts.views), so an
#: attacker cannot spend ten on each.
LOGIN_LIMIT = 10
LOGIN_WINDOW_SECONDS = 900


def _login_key(username: str) -> str:
    """The form `authenticate` treats as one account: Django's UsernameField strips
    and NFKC-normalizes, and the JSON door resolves case-insensitively, so every
    spelling of one account must share one bucket."""
    return unicodedata.normalize("NFKC", username.strip()).casefold()


def login_rate_limited(username: str) -> bool:
    """True once this username has been tried more than LOGIN_LIMIT times.

    Keyed on SHA-256 of the username: never the client address (a university's
    NAT would share one key) and never CRC32 (linear, so a crafted username
    could collide with a victim's and lock them out). auth_login's docstring
    carries the full reasoning.
    """
    return rate_limited(
        "api-login",
        int.from_bytes(hashlib.sha256(_login_key(username).encode()).digest()[:8], "big"),
        limit=LOGIN_LIMIT,
        window_seconds=LOGIN_WINDOW_SECONDS,
    )


#: Pack commands (reject, replace, consider) and application add and remove
#: share one per-student bucket, so round-robining between them dodges nothing.
#: Add and remove are in it because each add of a portal-less programme asks
#: the counsellor (final review M4).
PACK_COMMAND_LIMIT = 20
PACK_COMMAND_WINDOW_SECONDS = 60


def pack_command_rate_limited(student_id: UUID | int) -> bool:
    return rate_limited(
        "pack-command", student_id, limit=PACK_COMMAND_LIMIT,
        window_seconds=PACK_COMMAND_WINDOW_SECONDS,
    )
