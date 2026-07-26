"""Unified REST throttle valve — all officers must pass here before exchange REST.

Builds on ip_rest_cooldown: proactive budget + forced silence after rate-limit.
Keyed by exchange account (exchange + user), with _GLOBAL fuse for shared IP.

Production stance (multi-user × ETH+XAU): prefer ledger/WS; REST is scarce.
Budget is intentionally tight so we cool BEFORE exchange bans us.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.core.ip_rest_cooldown import (
    DEFAULT_COOL_SEC,
    note_rate_limit,
    remaining_sec,
    raise_if_cooling,
)

# Re-export for callers / tests
__all__ = [
    "DEFAULT_BUDGET_PER_MIN",
    "ThrottleDenied",
    "acquire_rest_permit",
    "require_rest_or_transient",
    "rest_silent",
    "sentinel_may_rest",
    "note_rate_limit",
    "remaining_sec",
    "record_rest_call",
    "calls_last_min",
    "reset_for_tests",
]

logger = logging.getLogger(__name__)

_lock = threading.RLock()
# key -> list of call timestamps (last 60s)
_calls: dict[str, list[float]] = {}

# Soft budget before we refuse — multi-user shared IP; stay well under exchange caps.
# Binance ~2400 weight/min; openOrders~40 → 80 calls/min was still too hot with WS ticks.
DEFAULT_BUDGET_PER_MIN = 40
# When budget trips, cool for the full shared window (not a short 60s blip).
BUDGET_COOL_SEC = float(DEFAULT_COOL_SEC)


def _acct_key(exchange: str | None, user_id: int | str | None) -> str:
    return f"{(exchange or 'binance').lower()}:{user_id if user_id is not None else 'ip'}"


def record_rest_call(*, exchange: str | None, user_id: int | str | None = None) -> None:
    k = _acct_key(exchange, user_id)
    now = time.time()
    with _lock:
        arr = [t for t in _calls.get(k, []) if t >= now - 60.0]
        arr.append(now)
        _calls[k] = arr[-200:]


def calls_last_min(*, exchange: str | None, user_id: int | str | None = None) -> int:
    k = _acct_key(exchange, user_id)
    now = time.time()
    with _lock:
        return sum(1 for t in _calls.get(k, []) if t >= now - 60.0)


def reset_for_tests() -> None:
    with _lock:
        _calls.clear()


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
) -> None:
    """Raise ThrottleDenied if REST must not proceed."""
    left = remaining_sec(exchange=exchange, user_id=user_id)
    if left > 0:
        raise ThrottleDenied(f"{exchange} cool-down {left:.0f}s ({op})", remaining=left)
    n = calls_last_min(exchange=exchange, user_id=user_id)
    if n >= int(budget_per_min):
        # Full cool — stop thrash across ETH+XAU / all users on IP
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
    record_rest_call(exchange=exchange, user_id=user_id)
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
) -> None:
    """Client entry: deny → ExchangeTransientError so callers fail-closed / use stale."""
    try:
        acquire_rest_permit(exchange=exchange, user_id=user_id, op=op)
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
    return float(remaining_sec(exchange=exchange, user_id=user_id) or 0) > 0


def sentinel_may_rest(*, exchange: str | None, user_id: int | str | None, trading_paused: bool) -> tuple[bool, str]:
    """巡检/哨兵：暂停、冷却或预算耗尽时禁止 REST；只读账本。"""
    if trading_paused:
        return False, "trading_paused"
    left = remaining_sec(exchange=exchange, user_id=user_id)
    if left > 0:
        return False, f"cool:{left:.0f}s"
    n = calls_last_min(exchange=exchange, user_id=user_id)
    if n >= DEFAULT_BUDGET_PER_MIN:
        return False, f"budget:{n}/{DEFAULT_BUDGET_PER_MIN}"
    return True, "ok"
