"""Breathing coefficient from locked TV atr (Gemini multi-user spec §7 / §14.12).

VPS no longer fetches exchange 1h ATR for radar. Coefficient stays at cold-start
(ratio=1.0 vs locked ``initial_atr`` = TV webhook atr). Fetch helpers kept as
no-op stubs for tests / legacy imports.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.breathing_stop import get_breathing_coefficient
from app.core.market_indicators import normalize_candle, wilder_atr

logger = logging.getLogger(__name__)

ATR_PERIOD = 14
KLINE_LIMIT = 100
REFRESH_SEC = 300.0  # legacy compat
RATIO_SMOOTH_N = 3

_lock = threading.RLock()
_cache: dict[str, dict[str, Any]] = {}


def breathing_coefficient_from_ratio(smooth_ratio: float, symbol: str | None = None) -> float:
    return get_breathing_coefficient(smooth_ratio, symbol)


def _cache_key(symbol: str | None) -> str:
    from app.core.symbol_registry import normalize_canonical_symbol

    can = normalize_canonical_symbol(symbol) or "ETHUSDT"
    return f"tv_atr:{can}"


def _fetch_1h_klines(client: Any, symbol: str | None) -> list:
    """LEGACY_PURGED — no VPS kline fetch for ATR (§14.12)."""
    _ = (client, symbol)
    return []


def compute_atr_1h_from_klines(klines: list) -> float:
    if not klines or len(klines) < ATR_PERIOD + 2:
        return 0.0
    try:
        candles = [normalize_candle(r) for r in klines]
    except Exception:
        return 0.0
    atr = float(wilder_atr(candles, period=ATR_PERIOD) or 0)
    return atr if atr > 0 else 0.0


def get_atr_1h(
    *,
    client: Any = None,
    exchange: str | None = None,
    symbol: str | None = None,
    force: bool = False,
) -> float:
    atr, _refreshed = get_atr_1h_with_meta(
        client=client, exchange=exchange, symbol=symbol, force=force,
    )
    return atr


def get_atr_1h_with_meta(
    *,
    client: Any = None,
    exchange: str | None = None,
    symbol: str | None = None,
    force: bool = False,
) -> tuple[float, bool]:
    """LEGACY_PURGED — always (0, False); use supervisor.initial_atr (TV)."""
    _ = (client, exchange, symbol, force)
    return 0.0, False


def update_breathing_coefficient(
    *,
    initial_atr: float,
    atr_1h: float,
    ratio_history: list[float] | None = None,
    symbol: str | None = None,
) -> tuple[float, list[float], float]:
    """Return (coef, updated_ratios, smooth_ratio)."""
    from app.core.breathing_profile import cold_start_multiplier, profile_for_symbol

    init = float(initial_atr or 0)
    cur = float(atr_1h or 0)
    ratios = list(ratio_history or [])
    p = profile_for_symbol(symbol)
    if init <= 0 or cur <= 0:
        smooth = 1.0
        coef = cold_start_multiplier(p)
        return coef, ratios[-RATIO_SMOOTH_N:], smooth

    ratio = cur / init
    ratios.append(ratio)
    if len(ratios) > RATIO_SMOOTH_N:
        ratios = ratios[-RATIO_SMOOTH_N:]
    smooth = sum(ratios) / len(ratios)
    coef = get_breathing_coefficient(smooth, symbol)
    return coef, ratios, smooth


def refresh_supervisor_breath(
    supervisor: Any,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Seed/keep cold-start breathing coefficient from locked TV ``initial_atr``.

    No exchange ATR fetch. Soft ticks do not expand ratio history.
    """
    from app.core.breathing_profile import cold_start_multiplier, profile_for_symbol

    _ = force
    init = float(getattr(supervisor, "initial_atr", 0) or 0)
    sym = (
        getattr(supervisor, "canonical_symbol", None)
        or getattr(supervisor, "symbol", None)
        or "ETHUSDT"
    )
    p = profile_for_symbol(sym)
    hist = list(getattr(supervisor, "breath_ratio_history", None) or [])
    # Locked TV atr vs itself → ratio 1.0 / cold-start multiplier
    smooth = 1.0
    coef = cold_start_multiplier(p)
    if not hist and init > 0:
        hist = [1.0]
    supervisor.atr_1h = init  # mirror locked TV atr (no second source)
    supervisor.breath_ratio_history = hist
    supervisor.breathing_coefficient = coef
    supervisor.breath_smooth_ratio = smooth
    return {
        "atr_1h": init,
        "initial_atr": init,
        "smooth_ratio": smooth,
        "breathing_coefficient": coef,
        "refreshed": False,
        "symbol": sym,
        "source": "tv_atr_locked",
    }


def reset_1h_atr_cache_for_tests() -> None:
    with _lock:
        _cache.clear()
