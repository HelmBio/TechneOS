"""Valkey (Redis-compatible) cache client."""

from typing import cast

import valkey.asyncio as valkey_async

from core.config import get_settings

_client: valkey_async.Valkey | None = None


async def get_valkey_client() -> valkey_async.Valkey:
    """Return a singleton async Valkey client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = valkey_async.from_url(
            settings.valkey_url,
            decode_responses=True,
        )
    return _client


async def close_valkey_client() -> None:
    """Close the Valkey client connection."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class Cache:
    """Simple caching interface over Valkey."""

    def __init__(self, client: valkey_async.Valkey, prefix: str = "techneos") -> None:
        self._client = client
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> str | None:
        """Get a value from cache."""
        return cast(str | None, await self._client.get(self._key(key)))

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        """Set a value in cache with TTL."""
        await self._client.set(self._key(key), value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        """Delete a value from cache."""
        await self._client.delete(self._key(key))

    async def incr(self, key: str) -> int:
        """Increment a counter."""
        return cast(int, await self._client.incr(self._key(key)))

    async def expire(self, key: str, ttl_seconds: int) -> None:
        """Set expiration on an existing key."""
        await self._client.expire(self._key(key), ttl_seconds)


class RateLimiter:
    """Token-bucket rate limiter backed by Valkey.

    Uses a sliding window counter approach.
    """

    def __init__(
        self,
        client: valkey_async.Valkey,
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> None:
        self._client = client
        self._max_requests = max_requests
        self._window = window_seconds

    async def is_allowed(self, identifier: str) -> tuple[bool, int]:
        """Check if a request is allowed for the given identifier.

        Returns (allowed: bool, remaining: int).
        """
        key = f"techneos:ratelimit:{identifier}"
        current = await self._client.incr(key)

        if current == 1:
            await self._client.expire(key, self._window)

        remaining = max(0, self._max_requests - current)
        return current <= self._max_requests, remaining
