"""Redis-backed REST throttle valve for distributed deployments.

Builds on redis_ip_cooldown: shared budget + forced silence after rate-limit.
All containers share the same budget counter and cooldown state.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import redis

from app.config import get_settings
from app.core.redis_ip_cooldown import (
    DEFAULT_COOL_SEC,
    note_rate_limit,
    remaining_sec,
    raise_if_cooling,
)

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None

BUDGET_COOL_SEC = float(DEFAULT_COOL_SEC)
# Budget reduced further to protect shared IP
DEFAULT_BUDGET_PER_MIN = 10  # was 15, now 10 for safety
EMERGENCY_BUDGET_PER_MIN = 20


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


def _acct_key(exchange: str | None, user_id: int | str | None) -> str:
    return f"rest:{(exchange or 'binance').lower()}:{user_id if user_id is not None else 'ip'}"


def record_rest_call(
    *,
    exchange: str | None,
    user_id: int | str | None = None,
    _emergency: bool = False,
) -> None:
    """Record a REST call in Redis sliding window."""
    k = _acct_key(exchange, user_id)
    now = time.time()
    prefix = "emg" if _emergency else "norm"
    key = f"rest:{prefix}:{k}"

    try:
        r = _get_redis()
        pipe = r.pipeline()
        pipe.zadd(key, {f"{now}": now})
        pipe.expire(key, 70)  # 60s window + 10s buffer
        pipe.execute()
    except redis.RedisError as e:
        logger.warning("Redis record_rest_call failed: %s", e)


def calls_last_min(
    *,
    exchange: str | None,
    user_id: int | str | None = None,
) -> int:
    """Count normal REST calls in last minute."""
    k = _acct_key(exchange, user_id)
    key = f"rest:norm:{k}"
    now = time.time()
    window_start = now - 60

    try:
        r = _get_redis()
        r.zremrangebyscore(key, 0, window_start)
        return r.zcard(key)
    except redis.RedisError as e:
        logger.warning("Redis calls_last_min failed: %s", e)
        return 0


def emergency_calls_last_min(
    *,
    exchange: str | None,
    user_id: int | str | None = None,
) -> int:
    """Count emergency REST calls in last minute."""
    k = _acct_key(exchange, user_id)
    key = f"rest:emg:{k}"
    now = time.time()
    window_start = now - 60

    try:
        r = _get_redis()
        r.zremrangebyscore(key, 0, window_start)
        return r.zcard(key)
    except redis.RedisError as e:
        logger.warning("Redis emergency_calls_last_min failed: %s", e)
        return 0


class ThrottleDenied(RuntimeError):
    def __init__(self, message: str, *, remaining: float = 0.0):
        super().__init__(message)
        self.remaining = remaining


def acquire_rest_permit(
    *,
    exchange: str | None,
    user_id: int | str | None = None,
    op: str = "rest",
    budget_per_min: int = DEFAULT_BUDGET_PER_MIN,
    priority: str = "normal",
) -> None:
    """Raise ThrottleDenied if REST must not proceed."""
    # Check cooldown first
    left = remaining_sec(exchange=exchange, user_id=user_id)
    if left > 0:
        raise ThrottleDenied(f"{exchange} cool-down {left:.0f}s ({op})", remaining=left)

    # Emergency calls bypass budget
    if priority != "emergency":
        n = calls_last_min(exchange=exchange, user_id=user_id)
        if n >= int(budget_per_min):
            note_rate_limit(
                exchange=exchange,
                user_id=user_id,
                cool_sec=BUDGET_COOL_SEC,
            )
            raise ThrottleDenied(
                f"{exchange} REST budget exceeded {n}/{budget_per_min} ({op})",
                remaining=BUDGET_COOL_SEC,
            )

    raise_if_cooling(exchange=exchange, user_id=user_id, op=op)

    # Record the call
    if priority != "emergency":
        record_rest_call(exchange=exchange, user_id=user_id)
    else:
        emergency_n = emergency_calls_last_min(exchange=exchange, user_id=user_id)
        if emergency_n >= EMERGENCY_BUDGET_PER_MIN:
            note_rate_limit(
                exchange=exchange,
                user_id=user_id,
                cool_sec=BUDGET_COOL_SEC,
            )
            raise ThrottleDenied(
                f"{exchange} emergency budget exceeded {emergency_n}/{EMERGENCY_BUDGET_PER_MIN}",
                remaining=BUDGET_COOL_SEC,
            )
        record_rest_call(exchange=exchange, user_id=user_id, _emergency=True)


def require_rest_or_transient(
    *,
    exchange: str | None,
    user_id: int | str | None = None,
    op: str = "rest",
    priority: str = "normal",
) -> None:
    """Client entry: deny → ExchangeTransientError."""
    try:
        acquire_rest_permit(exchange=exchange, user_id=user_id, op=op, priority=priority)
    except ThrottleDenied as e:
        from app.core.exchange_errors import ExchangeTransientError

        ban_ms = int((time.time() + float(getattr(e, "remaining", 0) or 0)) * 1000)
        raise ExchangeTransientError(
            str(e),
            exchange=exchange,
            code=-1003,
            banned_until_ms=ban_ms if getattr(e, "remaining", 0) else None,
        ) from e


def rest_silent(*, exchange: str | None, user_id: int | str | None = None) -> bool:
    """True when REST must not be initiated."""
    return float(remaining_sec(exchange=exchange, user_id=user_id) or 0) > 0


def sentinel_may_rest(
    *,
    exchange: str | None,
    user_id: int | str | None,
    trading_paused: bool,
    priority: str = "normal",
) -> tuple[bool, str]:
    """Sentinel check: return (allowed, reason)."""
    if trading_paused:
        return False, "trading_paused"
    left = remaining_sec(exchange=exchange, user_id=user_id)
    if left > 0:
        return False, f"cool:{left:.0f}s"
    if priority == "emergency":
        return True, "emergency_ok"
    n = calls_last_min(exchange=exchange, user_id=user_id)
    if n >= DEFAULT_BUDGET_PER_MIN:
        return False, f"budget:{n}/{DEFAULT_BUDGET_PER_MIN}"
    return True, "ok"


def reset_for_tests() -> None:
    """Clear all REST budget keys (for testing)."""
    try:
        r = _get_redis()
        keys = r.keys("rest:*")
        if keys:
            r.delete(*keys)
    except redis.RedisError as e:
        logger.warning("Redis reset_for_tests failed: %s", e)


# Re-export for compatibility
__all__ = [
    "DEFAULT_BUDGET_PER_MIN",
    "EMERGENCY_BUDGET_PER_MIN",
    "ThrottleDenied",
    "acquire_rest_permit",
    "require_rest_or_transient",
    "rest_silent",
    "sentinel_may_rest",
    "note_rate_limit",
    "remaining_sec",
    "record_rest_call",
    "calls_last_min",
    "emergency_calls_last_min",
    "reset_for_tests",
]
