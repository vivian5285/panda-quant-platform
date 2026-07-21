"""WebSocket reconnect backoff — checklist §十: 1s, 2s, 4s..."""

from __future__ import annotations

import time

WS_RECONNECT_BASE_SEC = 1.0
WS_RECONNECT_CAP_SEC = 60.0


def ws_reconnect_delay(attempt: int, *, base: float = WS_RECONNECT_BASE_SEC, cap: float = WS_RECONNECT_CAP_SEC) -> float:
    """Return sleep seconds for 0-based reconnect attempt (1, 2, 4, ... capped)."""
    n = max(0, int(attempt))
    return min(float(cap), float(base) * (2 ** n))


def sleep_ws_reconnect(attempt: int, *, base: float = WS_RECONNECT_BASE_SEC, cap: float = WS_RECONNECT_CAP_SEC) -> float:
    """Sleep with exponential backoff; return the delay used."""
    delay = ws_reconnect_delay(attempt, base=base, cap=cap)
    time.sleep(delay)
    return delay
