"""Unit tests for pure helpers (no database)."""

from datetime import UTC, date, datetime

import pytest

from app.core.cache import RedisCache
from app.core.errors import BadRequestError
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.core.timeutils import local_range_to_utc, period_bounds


@pytest.mark.parametrize(
    ("period", "reference", "expected"),
    [
        ("day", date(2026, 3, 4), (date(2026, 3, 4), date(2026, 3, 4))),
        ("week", date(2026, 3, 4), (date(2026, 3, 2), date(2026, 3, 8))),
        ("week", date(2026, 3, 8), (date(2026, 3, 2), date(2026, 3, 8))),
        ("month", date(2026, 2, 14), (date(2026, 2, 1), date(2026, 2, 28))),
        ("month", date(2028, 2, 14), (date(2028, 2, 1), date(2028, 2, 29))),
        ("month", date(2026, 12, 31), (date(2026, 12, 1), date(2026, 12, 31))),
    ],
)
def test_period_bounds(period, reference, expected):
    assert period_bounds(period, reference) == expected


def test_period_bounds_rejects_unknown():
    with pytest.raises(BadRequestError):
        period_bounds("year", date(2026, 1, 1))


def test_local_range_handles_dst():
    # US clocks spring forward on 2026-03-08, so that local day is only 23 hours long.
    start, end = local_range_to_utc(date(2026, 3, 8), date(2026, 3, 8), "America/New_York")
    assert start == datetime(2026, 3, 8, 5, tzinfo=UTC)
    assert end == datetime(2026, 3, 9, 4, tzinfo=UTC)


def test_password_hashing():
    hashed = hash_password("correct horse")
    assert hashed != "correct horse"
    assert verify_password("correct horse", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_token_round_trip():
    claims = decode_access_token(create_access_token(42))
    assert claims.user_id == 42 and claims.issued_at.tzinfo is not None


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_failure_limiter(backend):
    from app.core.cache import InMemoryCache, set_cache
    from app.core.ratelimit import FailureLimiter

    if backend == "redis":
        cache = RedisCache("redis://127.0.0.1:6379/0")
        if not cache.ping():
            pytest.skip("Redis is not running")
        set_cache(cache)
    else:
        set_cache(InMemoryCache())
    limiter = FailureLimiter(f"test-{backend}", max_failures=3, window_seconds=60)
    limiter.reset("k")
    try:
        for _ in range(2):
            limiter.record_failure("k")
        assert limiter.retry_after("k") == 0
        limiter.record_failure("k")
        assert 1 <= limiter.retry_after("k") <= 61
        assert limiter.retry_after("someone-else") == 0
        limiter.record_failure("k")  # more failures don't push the window further out
        assert limiter.retry_after("k") <= 61
        limiter.reset("k")
        assert limiter.retry_after("k") == 0
    finally:
        limiter.reset("k")


def test_redis_cache_degrades_gracefully_when_down():
    cache = RedisCache("redis://127.0.0.1:1/0")  # nothing listens on port 1
    assert cache.get_json("k") is None
    cache.set_json("k", {"a": 1}, 60)
    cache.delete_prefix("k")
    assert cache.ping() is False
