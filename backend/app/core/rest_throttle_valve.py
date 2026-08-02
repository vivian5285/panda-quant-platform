"""Unified REST throttle valve — all officers must pass here before exchange REST.

Builds on ip_rest_cooldown: proactive budget + forced silence after rate-limit.
Keyed by exchange account (exchange + user), with _GLOBAL fuse for shared IP.

Production stance (multi-user × ETH+XAU): prefer ledger/WS; REST is scarce.
Budget is intentionally tight so we cool BEFORE exchange bans us.

Redis-backed for distributed deployments (docker-compose scale).
Falls back to in-memory if Redis unavailable.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.core.ip_rest_cooldown import (
    DEFAULT_COOL_SEC,
    note_rate_limit as _mem_note,
    remaining_sec as _mem_remaining,
    raise_if_cooling as _mem_raise,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_calls: dict[str, list[float]] = {}
_emergency_calls: dict[str, list[float]] = {}

# Try Redis-backed implementation
_use_redis = False
_redis_note = None
_redis_remaining = None

try:
    from app.core.redis_rest_throttle import (
        note_rate_limit as _redis_note,
        remaining_sec as _redis_remaining,
        DEFAULT_BUDGET_PER_MIN as _REDIS_BUDGET,
        EMERGENCY_BUDGET_PER_MIN as _REDIS_EMG_BUDGET,
    )
    _use_redis = True
    logger.info("Using Redis-backed REST throttle (distributed mode)")
except ImportError:
    logger.warning("Redis not available, using in-memory REST throttle")

# Soft budget before we refuse — multi-user shared IP; stay well under exchange caps.
# Binance ~2400 weight/min; openOrders~40 weight.
# Redis mode: reduced to 8/min for safety in multi-container environment.
DEFAULT_BUDGET_PER_MIN = 8 if _use_redis else 12
EMERGENCY_BUDGET_PER_MIN = 16 if _use_redis else 24
BUDGET_COOL_SEC = float(DEFAULT_COOL_SEC)


def _acct_key(exchange: str | None, user_id: int | str | None) -> str:
    return f"{(exchange or 'binance').lower()}:{user_id if user_id is not None else 'ip'}"


def record_rest_call(*, exchange: str | None, user_id: int | str | None = None, _emergency: bool = False) -> None:
    if _use_redis:
        from app.core.redis_rest_throttle import record_rest_call as _r_record
        return _r_record(exchange=exchange, user_id=user_id, _emergency=_emergency)
    k = _acct_key(exchange, user_id)
    now = time.time()
    if _emergency:
        with _lock:
            arr = [t for t in _emergency_calls.get(k, []) if t >= now - 60.0]
            arr.append(now)
            _emergency_calls[k] = arr[-200:]
    else:
        with _lock:
            arr = [t for t in _calls.get(k, []) if t >= now - 60.0]
            arr.append(now)
            _calls[k] = arr[-200:]


def calls_last_min(*, exchange: str | None, user_id: int | str | None = None) -> int:
    if _use_redis:
        from app.core.redis_rest_throttle import calls_last_min as _r_calls
        return _r_calls(exchange=exchange, user_id=user_id)
    k = _acct_key(exchange, user_id)
    now = time.time()
    with _lock:
        return sum(1 for t in _calls.get(k, []) if t >= now - 60.0)


def emergency_calls_last_min(*, exchange: str | None, user_id: int | str | None = None) -> int:
    if _use_redis:
        from app.core.redis_rest_throttle import emergency_calls_last_min as _r_emg
        return _r_emg(exchange=exchange, user_id=user_id)
    k = _acct_key(exchange, user_id)
    now = time.time()
    with _lock:
        return sum(1 for t in _emergency_calls.get(k, []) if t >= now - 60.0)


def reset_for_tests() -> None:
    if _use_redis:
        from app.core.redis_rest_throttle import reset_for_tests as _r_reset
        return _r_reset()
    with _lock:
        _calls.clear()
        _emergency_calls.clear()


def remaining_sec(*, exchange: str | None = None, user_id: int | str | None = None) -> float:
    if _use_redis and _redis_remaining:
        return _redis_remaining(exchange=exchange, user_id=user_id)
    return _mem_remaining(exchange=exchange, user_id=user_id)


def note_rate_limit(**kwargs) -> float:
    if _use_redis and _redis_note:
        return _redis_note(**kwargs)
    return _mem_note(**kwargs)


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
    ledger: Any = None,
    priority: str = "normal",
) -> None:
    """Raise ThrottleDenied if REST must not proceed."""
    if _use_redis:
        from app.core.redis_rest_throttle import acquire_rest_permit as _r_acquire
        return _r_acquire(
            exchange=exchange, user_id=user_id, op=op,
            budget_per_min=budget_per_min, priority=priority
        )
    left = _mem_remaining(exchange=exchange, user_id=user_id)
    if left > 0:
        raise ThrottleDenied(f"{exchange} cool-down {left:.0f}s ({op})", remaining=left)
    if priority != "emergency":
        n = calls_last_min(exchange=exchange, user_id=user_id)
        if n >= int(budget_per_min):
            _mem_note(exchange=exchange, user_id=user_id, cool_sec=BUDGET_COOL_SEC)
            raise ThrottleDenied(
                f"{exchange} REST budget exceeded {n}/{budget_per_min} ({op})",
                remaining=BUDGET_COOL_SEC,
            )
    _mem_raise(exchange=exchange, user_id=user_id, op=op)
    if priority != "emergency":
        record_rest_call(exchange=exchange, user_id=user_id)
    else:
        emergency_n = emergency_calls_last_min(exchange=exchange, user_id=user_id)
        if emergency_n >= EMERGENCY_BUDGET_PER_MIN:
            _mem_note(exchange=exchange, user_id=user_id, cool_sec=BUDGET_COOL_SEC)
            raise ThrottleDenied(
                f"{exchange} emergency budget exceeded {emergency_n}/{EMERGENCY_BUDGET_PER_MIN}",
                remaining=BUDGET_COOL_SEC,
            )
        record_rest_call(exchange=exchange, user_id=user_id, _emergency=True)
    if ledger is not None and hasattr(ledger, "note_api_call"):
        try:
            ledger.note_api_call()
        except Exception:
            pass


def require_rest_or_transient(
    *,
    exchange: str | None,
    user_id: int | str | None = None,
    op: str = "rest",
    priority: str = "normal",
) -> None:
    """Client entry: deny → ExchangeTransientError so callers fail-closed / use stale."""
    if _use_redis:
        from app.core.redis_rest_throttle import require_rest_or_transient as _r_require
        return _r_require(exchange=exchange, user_id=user_id, op=op, priority=priority)
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
    """True when REST must not be initiated (cool)."""
    if _use_redis:
        from app.core.redis_rest_throttle import rest_silent as _r_silent
        return _r_silent(exchange=exchange, user_id=user_id)
    return float(_mem_remaining(exchange=exchange, user_id=user_id) or 0) > 0


def sentinel_may_rest(*, exchange: str | None, user_id: int | str | None, trading_paused: bool, priority: str = "normal") -> tuple[bool, str]:
    """巡检/哨兵：暂停、冷却或预算耗尽时禁止 REST；只读账本."""
    if _use_redis:
        from app.core.redis_rest_throttle import sentinel_may_rest as _r_sentinel
        return _r_sentinel(exchange=exchange, user_id=user_id, trading_paused=trading_paused, priority=priority)
    if trading_paused:
        return False, "trading_paused"
    left = _mem_remaining(exchange=exchange, user_id=user_id)
    if left > 0:
        return False, f"cool:{left:.0f}s"
    if priority == "emergency":
        return True, "emergency_ok"
    n = calls_last_min(exchange=exchange, user_id=user_id)
    if n >= DEFAULT_BUDGET_PER_MIN:
        return False, f"budget:{n}/{DEFAULT_BUDGET_PER_MIN}"
    return True, "ok"


# Re-export for callers / tests
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
