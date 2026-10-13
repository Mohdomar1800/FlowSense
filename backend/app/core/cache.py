"""Small JSON cache abstraction.

RedisCache is used in normal runs. If Redis is unreachable the app keeps working:
failures are logged and the cache backs off for a short period instead of slowing every request.
"""

import json
import logging
import time
from typing import Any, Protocol

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Cache(Protocol):
    def get_json(self, key: str) -> Any | None: ...
    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def ping(self) -> bool: ...


class NullCache:
    def get_json(self, key: str) -> Any | None:
        return None

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        return None

    def delete_prefix(self, prefix: str) -> None:
        return None

    def ping(self) -> bool:
        return False


class InMemoryCache:
    """Process-local cache; used in tests. TTL is ignored."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get_json(self, key: str) -> Any | None:
        raw = self.store.get(key)
        return json.loads(raw) if raw is not None else None

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.store[key] = json.dumps(value)

    def delete_prefix(self, prefix: str) -> None:
        for key in [k for k in self.store if k.startswith(prefix)]:
            del self.store[key]

    def ping(self) -> bool:
        return True


class RedisCache:
    BACKOFF_SECONDS = 30

    def __init__(self, url: str) -> None:
        self._client = Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5)
        self._down_until = 0.0

    def _available(self) -> bool:
        return time.monotonic() >= self._down_until

    def _mark_down(self, action: str) -> None:
        logger.warning("redis %s failed; caching disabled for %ss", action, self.BACKOFF_SECONDS)
        self._down_until = time.monotonic() + self.BACKOFF_SECONDS

    def get_json(self, key: str) -> Any | None:
        if not self._available():
            return None
        try:
            raw = self._client.get(key)
        except RedisError:
            self._mark_down("get")
            return None
        return json.loads(raw) if raw else None

    def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        if not self._available():
            return
        try:
            self._client.setex(key, ttl_seconds, json.dumps(value))
        except RedisError:
            self._mark_down("set")

    def delete_prefix(self, prefix: str) -> None:
        # Invalidation is attempted even while backing off, so stale data is never served after recovery.
        try:
            keys = list(self._client.scan_iter(match=f"{prefix}*", count=100))
            if keys:
                self._client.delete(*keys)
        except RedisError:
            self._mark_down("delete")

    def ping(self) -> bool:
        try:
            return bool(self._client.ping())
        except RedisError:
            return False


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        settings = get_settings()
        _cache = RedisCache(settings.redis_url) if settings.redis_enabled else NullCache()
    return _cache


def set_cache(cache: Cache) -> None:
    """Swap the cache implementation (tests)."""
    global _cache
    _cache = cache
