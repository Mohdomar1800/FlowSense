"""Failure-based rate limiting (used to slow down password guessing).

Only failures are counted, and a success clears the count, so a user who mistypes once is never
locked out of a correct login. Counts live in Redis when it's available (shared by every API
process) and otherwise in this process's memory.
"""

import threading
import time

from redis.exceptions import RedisError

from app.core.cache import RedisCache, get_cache


class FailureLimiter:
    def __init__(self, name: str, max_failures: int, window_seconds: int) -> None:
        self.name = name
        self.max_failures = max_failures
        self.window = window_seconds
        self._lock = threading.Lock()
        self._memory: dict[str, list[float]] = {}

    def _key(self, key: str) -> str:
        return f"ratelimit:{self.name}:{key}"

    def _redis(self):
        cache = get_cache()
        return cache._client if isinstance(cache, RedisCache) else None

    def retry_after(self, key: str) -> int:
        """Seconds until `key` may try again, or 0 if it isn't blocked."""
        client = self._redis()
        if client is not None:
            try:
                count = int(client.get(self._key(key)) or 0)
                return max(1, int(client.ttl(self._key(key)))) if count >= self.max_failures else 0
            except RedisError:
                pass
        with self._lock:
            recent = self._recent(key)
            return int(recent[0] + self.window - time.monotonic()) + 1 if len(recent) >= self.max_failures else 0

    def record_failure(self, key: str) -> None:
        client = self._redis()
        if client is not None:
            try:
                pipe = client.pipeline()
                pipe.incr(self._key(key))
                pipe.expire(self._key(key), self.window, nx=True)  # window starts at the first failure
                pipe.execute()
                return
            except RedisError:
                pass
        with self._lock:
            self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        client = self._redis()
        if client is not None:
            try:
                client.delete(self._key(key))
            except RedisError:
                pass
        with self._lock:
            self._memory.pop(key, None)

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        recent = [t for t in self._memory.get(key, []) if t > cutoff]
        self._memory[key] = recent
        return recent


# 8 wrong passwords per account and client address within 15 minutes, then wait out the rest of the window.
login_limiter = FailureLimiter("login", max_failures=8, window_seconds=15 * 60)
