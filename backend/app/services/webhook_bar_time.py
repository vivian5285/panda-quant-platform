"""Optional webhook bar_time freshness / out-of-order guard (per symbol).

When TV sends ``bar_time`` (K-line time ms), reject messages older than the
latest accepted bar_time for that symbol. Missing bar_time is a no-op
(non-blocking; coalesce + idempotency still apply).
"""

from __future__ import annotations

import threading
from typing import Any

from app.config import get_settings
from app.core.symbol_registry import normalize_canonical_symbol

_lock = threading.RLock()
_last_bar_time_ms: dict[str, int] = {}


def reset_bar_time_gate_for_tests() -> None:
    with _lock:
        _last_bar_time_ms.clear()


def coerce_bar_time_ms(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    # Pine often sends seconds; ms are ~1e12+
    if v < 1e11:
        v *= 1000.0
    return int(v)


def note_bar_time_watermark(
    *,
    symbol: str | None,
    bar_time: Any,
) -> None:
    """Advance per-symbol watermark without rejecting (used for CLOSE)."""
    bt = coerce_bar_time_ms(bar_time)
    if bt is None:
        return
    can = normalize_canonical_symbol(symbol) or str(symbol or "").upper() or "_"
    with _lock:
        last = _last_bar_time_ms.get(can)
        _last_bar_time_ms[can] = max(last or 0, bt)


def check_and_accept_bar_time(
    *,
    symbol: str | None,
    bar_time: Any,
    enabled: bool | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Return (ok, reason, meta). On ok with bar_time present, advances watermark."""
    settings = get_settings()
    if enabled is None:
        enabled = bool(getattr(settings, "WEBHOOK_BAR_TIME_ENABLED", True))
    meta: dict[str, Any] = {"bar_time": None, "last_bar_time": None}
    if not enabled:
        return True, "disabled", meta

    bt = coerce_bar_time_ms(bar_time)
    meta["bar_time"] = bt
    if bt is None:
        return True, "no_bar_time", meta

    can = normalize_canonical_symbol(symbol) or str(symbol or "").upper() or "_"
    with _lock:
        last = _last_bar_time_ms.get(can)
        meta["last_bar_time"] = last
        meta["symbol"] = can
        if last is not None and bt < last:
            return False, "stale_bar_time", meta
        _last_bar_time_ms[can] = max(last or 0, bt)
        return True, "accepted", meta
