"""Per-symbol REST spacing — whitepaper v3 §8.3.

Single-symbol REST gap must be ≥100ms. Also respects shared IP cool-down
after -1003 (see ``ip_rest_cooldown``).

Shared all-account endpoints (``_all_orders`` / ``_all_positions``) use a
longer gap so dual ETH+XAU supervisors cannot double-hit weight-40 openOrders.
"""

from __future__ import annotations

import threading
import time
from typing import Any

MIN_GAP_SEC = 0.100  # whitepaper §8.3
# Shared all-account endpoints (openOrders ~weight 40) need stronger pacing.
SHARED_ACCOUNT_GAP_SEC = 2.0

_lock = threading.RLock()
# key -> last_request_monotonic
_last_mono: dict[str, float] = {}


def _key(
    *,
    exchange: str | None,
    user_id: int | str | None,
    symbol: str | None,
) -> str:
    ex = (exchange or "binance").lower()
    uid = str(user_id if user_id is not None else "ip")
    sym = (symbol or "_").upper().replace("/", "").replace(":USDT", "")
    if sym.endswith("USDT.P"):
        sym = sym[:-2]
    return f"{ex}:{uid}:{sym}"


def wait_turn(
    *,
    exchange: str | None = "binance",
    user_id: int | str | None = None,
    symbol: str | None = None,
    min_gap_sec: float | None = None,
) -> float:
    """Sleep so consecutive REST for this symbol stay ≥min_gap apart.

    IP cool-down (-1003) is handled by ``ip_rest_cooldown`` — callers check that
    separately. Returns seconds slept (0 if no wait).
    """
    sym = str(symbol or "")
    if min_gap_sec is not None:
        gap = max(0.0, float(min_gap_sec))
    elif sym.startswith("_all_"):
        gap = SHARED_ACCOUNT_GAP_SEC
    else:
        gap = MIN_GAP_SEC
    k = _key(exchange=exchange, user_id=user_id, symbol=symbol)
    slept = 0.0
    with _lock:
        now = time.monotonic()
        last = float(_last_mono.get(k) or 0.0)
        need = gap - (now - last) if last > 0 else 0.0
        if need > 0:
            time.sleep(need)
            slept = need
            now = time.monotonic()
        _last_mono[k] = now
    return slept


def note_request(
    *,
    exchange: str | None = "binance",
    user_id: int | str | None = None,
    symbol: str | None = None,
) -> None:
    """Mark a REST call completed (when wait_turn was not used up-front)."""
    k = _key(exchange=exchange, user_id=user_id, symbol=symbol)
    with _lock:
        _last_mono[k] = time.monotonic()


def reset_for_tests() -> None:
    with _lock:
        _last_mono.clear()


def snapshot() -> dict[str, Any]:
    now = time.monotonic()
    with _lock:
        return {k: max(0.0, now - v) for k, v in _last_mono.items()}
