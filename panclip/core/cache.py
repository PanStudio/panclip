"""Search result cache, invalidated by a generation counter that every write bumps."""

import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

PREFIX = "panclip:"


def search_key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


class MemoryCache:
    """In-process LRU with per-entry expiry."""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.generation = 0

    async def get_generation(self) -> int:
        return self.generation

    async def bump_generation(self) -> None:
        self.generation += 1
        self.entries.clear()

    async def get(self, key: str) -> Any | None:
        entry = self.entries.get(key)
        if entry is None:
            return None
        if entry[0] < time.monotonic():
            del self.entries[key]
            return None
        self.entries.move_to_end(key)
        return entry[1]

    async def set(self, key: str, value: Any, ttl: int) -> None:
        self.entries[key] = (time.monotonic() + ttl, value)
        self.entries.move_to_end(key)
        while len(self.entries) > self.max_size:
            self.entries.popitem(last=False)

    async def close(self) -> None:
        self.entries.clear()


class RedisCache:
    """Shared cache at a configured Redis URL; any Redis failure is a cache miss."""

    def __init__(self, url: str):
        import redis.asyncio as redis

        self.redis = redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
        )

    async def _try(self, operation, default=None):
        try:
            return await operation
        except Exception as error:
            logger.warning("redis cache unavailable: %s", type(error).__name__)
            return default

    async def get_generation(self) -> int:
        value = await self._try(self.redis.get(PREFIX + "gen"))
        return int(value or 0)

    async def bump_generation(self) -> None:
        await self._try(self.redis.incr(PREFIX + "gen"))

    async def get(self, key: str) -> Any | None:
        value = await self._try(self.redis.get(PREFIX + key))
        return json.loads(value) if value else None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        await self._try(self.redis.set(PREFIX + key, json.dumps(value), ex=ttl))

    async def close(self) -> None:
        await self._try(self.redis.aclose())


class SearchCache:
    """Caches search results under the current write generation."""

    def __init__(self, redis_url: str | None = None, ttl: int = 600):
        self.ttl = ttl
        self.backend = RedisCache(redis_url) if redis_url else MemoryCache()

    @property
    def kind(self) -> str:
        return "redis" if isinstance(self.backend, RedisCache) else "memory"

    async def lookup(self, *parts: Any) -> tuple[str, Any | None]:
        """The cached value, and the key to store a fresh one under; a write in between orphans the key."""
        generation = await self.backend.get_generation()
        key = f"search:{generation}:{search_key(*parts)}"
        return key, await self.backend.get(key)

    async def store(self, key: str, value: Any) -> None:
        await self.backend.set(key, value, self.ttl)

    async def invalidate(self) -> None:
        await self.backend.bump_generation()

    async def close(self) -> None:
        await self.backend.close()
