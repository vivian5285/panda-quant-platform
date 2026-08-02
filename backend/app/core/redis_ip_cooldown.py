"""Redis-backed IP REST cooldown for distributed Binance protection.

Replaces in-memory cooldown tracking with Redis for:
1. Cross-container shared state (all supervisors see same cooldown)
2. Persistent cooldown across container restarts
3. Automatic expiry of stale cooldown entries
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import redis

from app.config import get_settings

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None

DEFAULT_COOL_SEC = 180.0
GLOBAL_SUFFIX = "_GLOBAL"


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


def _cool_key(exchange: str | None, user_id: int | str | None = None) -> str:
    """Generate cooldown key for Redis."""
    ex = (exchange or "binance").lower()
    if user_id is None:
        return f"cool:{ex}:ip"
    if str(user_id) == GLOBAL_SUFFIX:
        return f"cool:{ex}:{GLOBAL_SUFFIX}"
    return f"cool:{ex}:{int(user_id)}"


def note_rate_limit(
    *,
    exchange: str | None = "binance",
    user_id: int | str | None = None,
    cool_sec: float = DEFAULT_COOL_SEC,
    banned_until_ms: int | None = None,
) -> float:
    """Extend cool-down in Redis; return cool_until epoch seconds.

    Broadcasts to user + IP + _GLOBAL so ETH/XAU (all supervisors) pause together.
    """
    now = time.time()
    if banned_until_ms:
        until = max(now + 5.0, float(banned_until_ms) / 1000.0)
    else:
        until = now + float(cool_sec or DEFAULT_COOL_SEC)

    try:
        r = _get_redis()
        k = _cool_key(exchange, user_id)
        k_ip = _cool_key(exchange, None)
        k_global = _cool_key(exchange, GLOBAL_SUFFIX)

        pipe = r.pipeline()
        for key in (k, k_ip, k_global):
            # Use ZADD with XX flag to only update if exists, GT to only if greater
            # Simpler approach: GET then SET
            pass

        # Get current values and set max
        for key in (k, k_ip, k_global):
            existing = r.zscore(key, "until") or 0
            new_until = max(float(existing), until)
            r.zadd(key, {"until": new_until})
            r.expire(key, int(DEFAULT_COOL_SEC) + 60)

        return float(r.zscore(k_global, "until") or until)

    except redis.RedisError as e:
        logger.error("Redis note_rate_limit failed: %s", e)
        # Fall back to returning the computed until value
        return until


def remaining_sec(
    *,
    exchange: str | None = "binance",
    user_id: int | str | None = None,
) -> float:
    """Return seconds until cooldown expires (0 if not cooling)."""
    now = time.time()
    try:
        r = _get_redis()
        k_user = _cool_key(exchange, user_id)
        k_ip = _cool_key(exchange, None)
        k_global = _cool_key(exchange, GLOBAL_SUFFIX)

        # Get max of all three cooldown times
        until_user = r.zscore(k_user, "until") or 0
        until_ip = r.zscore(k_ip, "until") or 0
        until_global = r.zscore(k_global, "until") or 0

        until = max(until_user, until_ip, until_global)
        left = until - now
        return left if left > 0 else 0.0

    except redis.RedisError as e:
        logger.warning("Redis remaining_sec failed: %s", e)
        return 0.0  # Fail open


def raise_if_cooling(
    *,
    exchange: str | None = "binance",
    user_id: int | str | None = None,
    op: str = "rest",
) -> None:
    """Raise ExchangeTransientError if currently cooling."""
    left = remaining_sec(exchange=exchange, user_id=user_id)
    if left <= 0:
        return
    from app.core.exchange_errors import ExchangeTransientError

    ban_ms = int((time.time() + left) * 1000)
    raise ExchangeTransientError(
        f"{exchange or 'binance'} {op} blocked: IP cool-down {left:.0f}s (-1003)",
        exchange=exchange,
        code=-1003,
        banned_until_ms=ban_ms,
    )


def reset_for_tests() -> None:
    """Clear all cooldown entries (for testing)."""
    try:
        r = _get_redis()
        keys = r.keys("cool:*")
        if keys:
            r.delete(*keys)
    except redis.RedisError as e:
        logger.warning("Redis reset_for_tests failed: %s", e)


def snapshot() -> dict[str, Any]:
    """Get snapshot of all active cooldowns."""
    now = time.time()
    result = {}
    try:
        r = _get_redis()
        keys = r.keys("cool:*")
        for key in keys:
            until = r.zscore(key, "until") or 0
            left = until - now
            if left > 0:
                result[key] = left
    except redis.RedisError as e:
        logger.warning("Redis snapshot failed: %s", e)
    return result
