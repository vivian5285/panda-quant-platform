"""Unified REST throttle valve — all officers must pass here before exchange REST.

Builds on ip_rest_cooldown: proactive budget + forced silence after rate-limit.
Keyed by exchange account (exchange + user), with _GLOBAL fuse for shared IP.
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

logger = logging.getLogger(__name__)

_lock = threading.RLock()
# key -> list of call timestamps (last 60s)
_calls: dict[str, list[float]] = {}

# Soft budget before we refuse (Binance weight is complex; count is a fuse).
DEFAULT_BUDGET_PER_MIN = 80


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
    """Raise ThrottleDenied / ExchangeTransientError if REST must not proceed."""
    left = remaining_sec(exchange=exchange, user_id=user_id)
    if left > 0:
        raise ThrottleDenied(f"{exchange} cool-down {left:.0f}s ({op})", remaining=left)
    n = calls_last_min(exchange=exchange, user_id=user_id)
    if n >= int(budget_per_min):
        # Enter shared cool to stop thrash
        note_rate_limit(exchange=exchange, user_id=user_id, cool_sec=min(60.0, DEFAULT_COOL_SEC))
        raise ThrottleDenied(
            f"{exchange} REST budget exceeded {n}/{budget_per_min} ({op})",
            remaining=60.0,
        )
    raise_if_cooling(exchange=exchange, user_id=user_id, op=op)
    record_rest_call(exchange=exchange, user_id=user_id)
    if ledger is not None and hasattr(ledger, "note_api_call"):
        try:
            ledger.note_api_call()
        except Exception:
            pass


def sentinel_may_rest(*, exchange: str | None, user_id: int | str | None, trading_paused: bool) -> tuple[bool, str]:
    """巡检/哨兵：暂停或冷却时禁止 REST；只读账本。"""
    if trading_paused:
        return False, "trading_paused"
    left = remaining_sec(exchange=exchange, user_id=user_id)
    if left > 0:
        return False, f"cool:{left:.0f}s"
    return True, "ok"
