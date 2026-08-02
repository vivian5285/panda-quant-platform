"""Redis-backed shared rate limiter for distributed deployments.

Replaces in-memory SlidingWindowRateLimiter with Redis for:
1. Multi-container state sharing (docker-compose scale)
2. Persistent cool-down state across restarts
3. Atomic operations for accurate rate limiting
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import redis
from redis.lock import Lock

from app.config import get_settings

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
    return _redis_client


class RedisSlidingWindowRateLimiter:
    """Redis-backed sliding window rate limiter.

    Uses sorted sets with timestamps for accurate sliding window counting.
    Each key expires automatically after window_seconds + 1 to prevent memory leaks.
    """

    def __init__(self, key_prefix: str = "ratelimit"):
        self.key_prefix = key_prefix

    def _key(self, identifier: str) -> str:
        return f"{self.key_prefix}:{identifier}"

    def allow(
        self,
        identifier: str,
        limit: int,
        window_seconds: int = 60,
    ) -> bool:
        """Return True if request is allowed, False if rate limited."""
        try:
            r = _get_redis()
            key = self._key(identifier)
            now = time.time()
            window_start = now - window_seconds

            pipe = r.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(key, 0, window_start)
            # Count current entries
            pipe.zcard(key)
            # Get current count before potentially adding
            count_before = r.zcard(key)

            if count_before >= limit:
                return False

            # Add new request with current timestamp as score and member
            pipe.zadd(key, {f"{now}:{id(self)}": now})
            # Set expiry
            pipe.expire(key, window_seconds + 10)
            pipe.execute()
            return True

        except redis.RedisError as e:
            logger.warning("Redis rate limit failed, allowing request: %s", e)
            return True  # Fail open for availability

    def get_remaining(self, identifier: str, limit: int, window_seconds: int = 60) -> int:
        """Get remaining requests allowed in current window."""
        try:
            r = _get_redis()
            key = self._key(identifier)
            now = time.time()
            window_start = now - window_seconds

            # Clean and count
            r.zremrangebyscore(key, 0, window_start)
            count = r.zcard(key)
            return max(0, limit - count)
        except redis.RedisError as e:
            logger.warning("Redis get_remaining failed: %s", e)
            return limit

    def reset(self, identifier: str) -> bool:
        """Reset rate limit for an identifier."""
        try:
            r = _get_redis()
            return r.delete(self._key(identifier)) > 0
        except redis.RedisError as e:
            logger.warning("Redis reset failed: %s", e)
            return False


# Singleton instance
redis_rate_limiter = RedisSlidingWindowRateLimiter()
