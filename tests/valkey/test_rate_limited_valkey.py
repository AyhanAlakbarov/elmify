"""Runs apps.ratelimit.rate_limited against a real Redis/Valkey backend --
what the node-based Valkey replication group (cluster mode disabled) is in
production (infra/template.yaml's `Cache` resource). This is the review
finding DatabaseCache failed on: a fixed window must keep its expiry across
increments, and two processes incrementing the same counter must both be
counted, not lost to a get-then-set race.

Needs a running server: `docker compose up -d valkey` then
`CACHE_URL=redis://localhost:6379/0`. Skipped cleanly, everywhere else,
without both.
"""

import os
import time
import uuid

import pytest
from django.core.cache.backends.redis import RedisCache
from django.test import override_settings

CACHE_URL = os.environ.get("CACHE_URL", "")

pytestmark = pytest.mark.skipif(
    not CACHE_URL, reason="CACHE_URL not set -- docker compose up -d valkey"
)


def _client() -> RedisCache:
    """A fresh RedisCache instance with its own connection pool, standing in
    for a separate ECS task -- not django.core.cache.cache, which would be one
    shared Python-level instance and could not show a cross-process race."""
    return RedisCache(CACHE_URL, {})


@pytest.fixture(autouse=True)
def _real_valkey_settings():
    """config/settings/test.py forces LocMemCache (a developer shell's own
    CACHE_URL must never point the WHOLE suite at a real server -- its autouse
    cache.clear() fixtures would FLUSHDB it). This module is the one exception:
    it overrides settings.CACHES back to the real backend so apps.ratelimit's
    module-level `cache` (imported once, at apps.ratelimit's own import time)
    resolves through Django's lazy cache handle to Valkey for the duration of
    each test here, exactly as production's settings would."""
    with override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": CACHE_URL,
            }
        }
    ):
        _client().clear()
        yield
        _client().clear()


def test_the_window_survives_idle_time_between_increments() -> None:
    """The bug DatabaseCache had: incr() resetting the key's expiry to
    Django's 300s default instead of keeping the window's own timeout."""
    from apps.ratelimit import rate_limited

    actor = uuid.uuid4()
    # A short window: long enough to run several increments, short enough that
    # a test can wait past it without a real 300s sleep.
    for _ in range(3):
        assert rate_limited("valkey-window", actor, limit=3, window_seconds=2) is False
    assert rate_limited("valkey-window", actor, limit=3, window_seconds=2) is True

    # The key's TTL is still bounded by the window, not reset to 300s.
    raw = _client()._cache.get_client(write=False)
    key = raw.keys("*ratelimit:valkey-window*")[0]
    ttl = raw.ttl(key)
    assert 0 < ttl <= 2


def test_two_independent_clients_both_count_toward_the_same_limit() -> None:
    """Two separate RedisCache instances, standing in for two ECS tasks.
    DatabaseCache's get-then-set incr can lose one side of this race; Redis's
    INCR is atomic and must not."""
    from apps.ratelimit import rate_limited

    actor = uuid.uuid4()
    bucket = "valkey-cross-process"

    # First client opens the window (count -> 1).
    assert rate_limited(bucket, actor, limit=9, window_seconds=60) is False

    # A second, independent client increments the same key several times
    # (count -> 9). The key carries the window index apps.ratelimit.rate_limited
    # itself computes (N2, 2026-09-27 re-review) -- window_seconds=60 here, so
    # both this call and the one above land in the same window barring a
    # once-a-minute flake.
    other = _client()
    window = int(time.time() // 60)
    key = f"ratelimit:{bucket}:{actor}:{window}"
    for _ in range(8):
        other.incr(key)

    # Back on the first client: the tenth increment must reflect all nine
    # that came before, not just this client's own one, so 10 > limit(9) trips.
    assert rate_limited(bucket, actor, limit=9, window_seconds=60) is True
