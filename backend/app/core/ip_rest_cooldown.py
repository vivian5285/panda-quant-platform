"""Process-wide Binance REST cool-down after -1003 (shared by ETH+XAU).

Binance often returns -1003 without a ``banned until`` timestamp. Without a
shared cool-down, dual sentinels sleep 15s then hammer again → permanent 2400/min.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.RLock()
# key -> cool_until_epoch_sec
_cool_until: dict[str, float] = {}

DEFAULT_COOL_SEC = 90.0


def _key(exchange: str | None, user_id: int | str | None = None) -> str:
    ex = (exchange or "binance").lower()
    if user_id is None:
        return f"{ex}:ip"
    return f"{ex}:{int(user_id)}"


def note_rate_limit(
    *,
    exchange: str | None = "binance",
    user_id: int | str | None = None,
    cool_sec: float = DEFAULT_COOL_SEC,
    banned_until_ms: int | None = None,
) -> float:
    """Extend cool-down; return cool_until epoch seconds."""
    now = time.time()
    if banned_until_ms:
        until = max(now + 5.0, float(banned_until_ms) / 1000.0)
    else:
        until = now + float(cool_sec or DEFAULT_COOL_SEC)
    k = _key(exchange, user_id)
    k_ip = _key(exchange, None)
    with _lock:
        for key in (k, k_ip):
            prev = float(_cool_until.get(key) or 0)
            _cool_until[key] = max(prev, until)
        return float(_cool_until[k_ip])


def remaining_sec(
    *,
    exchange: str | None = "binance",
    user_id: int | str | None = None,
) -> float:
    now = time.time()
    with _lock:
        until = max(
            float(_cool_until.get(_key(exchange, user_id)) or 0),
            float(_cool_until.get(_key(exchange, None)) or 0),
        )
    left = until - now
    return left if left > 0 else 0.0


def raise_if_cooling(
    *,
    exchange: str | None = "binance",
    user_id: int | str | None = None,
    op: str = "rest",
) -> None:
    left = remaining_sec(exchange=exchange, user_id=user_id)
    if left <= 0:
        return
    from app.core.exchange_errors import ExchangeTransientError

    ban_ms = int((time.time() + left) * 1000)
    raise ExchangeTransientError(
        f"{exchange or 'binance'} {op} blocked: IP cool-down {left:.0f}s left (-1003)",
        exchange=exchange,
        code=-1003,
        banned_until_ms=ban_ms,
    )


def reset_for_tests() -> None:
    with _lock:
        _cool_until.clear()


def snapshot() -> dict[str, Any]:
    now = time.time()
    with _lock:
        return {k: max(0.0, v - now) for k, v in _cool_until.items()}
