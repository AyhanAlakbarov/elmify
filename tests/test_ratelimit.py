from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.ratelimit import rate_limited


def test_the_limit_trips_after_the_configured_count() -> None:
    actor = uuid4()
    for _ in range(3):
        assert rate_limited("t-basic", actor, limit=3, window_seconds=60) is False
    assert rate_limited("t-basic", actor, limit=3, window_seconds=60) is True


def test_a_key_that_vanishes_between_add_and_incr_is_treated_as_a_fresh_window() -> None:
    """Redis's own INCR is atomic; the race this guards is between the two
    separate add()/incr() calls in rate_limited itself, at the window boundary.
    Django's RedisCache.incr raises ValueError when the key does not exist
    (django/core/cache/backends/redis.py); simulated here since LocMemCache
    (the test backend) cannot be made to lose the key mid-call."""
    actor = uuid4()
    real_incr = cache.incr
    calls = {"n": 0}

    def _flaky_incr(key: str, *args: object, **kwargs: object) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("gone")
        return real_incr(key)

    with patch("apps.ratelimit.cache.incr", side_effect=_flaky_incr) as incr:
        assert rate_limited("t-race", actor, limit=5, window_seconds=60) is False
        assert incr.call_count == 2


def test_a_backend_failure_is_not_swallowed_into_an_allowed_action() -> None:
    """Fail closed: a rate limit or spend cap that cannot be checked must
    refuse, never let the caller through unmetered."""
    actor = uuid4()
    with patch("apps.ratelimit.cache.add", side_effect=ConnectionError("valkey unreachable")):
        with pytest.raises(ConnectionError):
            rate_limited("t-down", actor, limit=5, window_seconds=60)


def test_a_key_recreated_without_ttl_does_not_block_the_next_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """N2 (2026-09-27 re-review): Django's RedisCacheClient.incr checks EXISTS
    and then runs INCR as two separate commands (django/core/cache/backends/
    redis.py). If the key expires between them, Redis's INCR recreates it at 1
    with NO expiry. Without a window index in the key, that stray key would
    make every future cache.add() (a SET NX) for this bucket/actor fail
    forever -- permanent lockout, not just a lost window. Embedding the window
    index bounds the damage to the one window that raced: the next window
    computes a different key and is unaffected.

    Simulates the race directly (a key with no TTL, as the lost EXISTS would
    leave it) rather than reproducing RedisCacheClient's internals -- LocMemCache
    (the test backend) has no EXISTS-then-INCR race of its own to trigger.
    """
    actor = uuid4()
    bucket = "t-leak"
    window_seconds = 60
    now = {"t": 1_700_000_000.0}
    monkeypatch.setattr("apps.ratelimit.time.time", lambda: now["t"])

    stuck_window = int(now["t"] // window_seconds)
    leaked_key = f"ratelimit:{bucket}:{actor}:{stuck_window}"
    cache.set(leaked_key, 5, timeout=None)  # no TTL -- what the race leaves behind
    assert rate_limited(bucket, actor, limit=3, window_seconds=window_seconds) is True

    # A new window: a different key, untouched by the one still stuck with no TTL.
    now["t"] += window_seconds
    assert rate_limited(bucket, actor, limit=3, window_seconds=window_seconds) is False
