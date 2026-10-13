"""Real-time user events (session changes, distractions) pushed to connected clients over WebSocket.

Services call `publish_user_event` after committing a change. Delivery goes through a broker:

- RedisBroker: Redis pub/sub, so an event published by any API process reaches clients connected
  to any other process. Used whenever Redis is enabled.
- LocalBroker: in-process queues, for single-process runs and tests. RedisBroker also delivers
  through it, so clients that connected while Redis was unreachable still get live updates.

Services run in worker threads while WebSockets live on the event loop, so local delivery hands
messages to the loop with call_soon_threadsafe.
"""

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Protocol

from redis import Redis
from redis import asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

QUEUE_SIZE = 100


class Broker(Protocol):
    def publish(self, user_id: int, message: dict[str, Any]) -> None: ...
    def subscribe(self, user_id: int): ...  # async context manager yielding an async iterator of messages


class LocalBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}

    def publish(self, user_id: int, message: dict[str, Any]) -> None:
        with self._lock:
            targets = list(self._subscribers.get(user_id, ()))
        for loop, queue in targets:
            loop.call_soon_threadsafe(_offer, queue, message)

    @asynccontextmanager
    async def subscribe(self, user_id: int) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        entry = (asyncio.get_running_loop(), asyncio.Queue(maxsize=QUEUE_SIZE))
        with self._lock:
            self._subscribers.setdefault(user_id, set()).add(entry)
        try:
            yield _drain(entry[1])
        finally:
            with self._lock:
                subscribers = self._subscribers.get(user_id)
                if subscribers is not None:
                    subscribers.discard(entry)
                    if not subscribers:
                        del self._subscribers[user_id]


def _offer(queue: asyncio.Queue, message: dict[str, Any]) -> None:
    # A slow client should not grow memory without bound: drop the oldest message instead.
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(message)


async def _drain(queue: asyncio.Queue) -> AsyncIterator[dict[str, Any]]:
    while True:
        yield await queue.get()


def _channel(user_id: int) -> str:
    return f"flowsense:user:{user_id}:events"


class RedisBroker:
    def __init__(self, url: str, fallback: LocalBroker) -> None:
        self._url = url
        self._client = Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5)
        self._fallback = fallback

    def publish(self, user_id: int, message: dict[str, Any]) -> None:
        # Every subscriber listens on exactly one path (Redis, or local after a failed Redis subscribe),
        # so publishing on both reaches everyone once, even if Redis was down when they connected.
        self._fallback.publish(user_id, message)
        try:
            self._client.publish(_channel(user_id), json.dumps(message))
        except RedisError:
            logger.warning("redis publish failed; only local subscribers were notified")

    @asynccontextmanager
    async def subscribe(self, user_id: int) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        client = aioredis.Redis.from_url(self._url, socket_connect_timeout=0.5)
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            await pubsub.subscribe(_channel(user_id))
        except (RedisError, OSError):
            logger.warning("redis subscribe failed; using local events")
            await client.aclose()
            async with self._fallback.subscribe(user_id) as messages:
                yield messages
            return

        async def messages() -> AsyncIterator[dict[str, Any]]:
            async for raw in pubsub.listen():
                yield json.loads(raw["data"])

        try:
            yield messages()
        finally:
            await pubsub.aclose()
            await client.aclose()


_broker: Broker | None = None


def get_broker() -> Broker:
    global _broker
    if _broker is None:
        settings = get_settings()
        local = LocalBroker()
        _broker = RedisBroker(settings.redis_url, local) if settings.redis_enabled else local
    return _broker


def set_broker(broker: Broker) -> None:
    """Swap the broker implementation (tests)."""
    global _broker
    _broker = broker


def publish_user_event(user_id: int, event_type: str, payload: dict[str, Any]) -> None:
    try:
        get_broker().publish(user_id, {"type": event_type, **payload})
    except Exception:  # live updates must never break the request that triggered them
        logger.exception("failed to publish %s event", event_type)
