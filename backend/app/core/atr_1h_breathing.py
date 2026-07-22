"""Binance native 1h ATR + breathing coefficient (radar upgrade).

initial_atr = TV webhook atr (fixed at open).
current_atr_1h = Binance GET /fapi/v1/klines interval=1h ATR(14).
breathing_coefficient = f(sma(current_atr_1h / initial_atr, 3)).

All exchanges share Binance public 1h klines as the volatility oracle.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from app.core.breathing_stop import get_breathing_coefficient
from app.core.market_engine import BINANCE_FAPI_KLINES, binance_public_klines
from app.core.market_indicators import normalize_candle, wilder_atr
from app.core.symbol_registry import normalize_canonical_symbol

logger = logging.getLogger(__name__)

ATR_PERIOD = 14
KLINE_LIMIT = 100
REFRESH_SEC = 300.0  # 5 minutes
RATIO_SMOOTH_N = 3

_lock = threading.RLock()
# key -> {atr, fetched_at, ratios: list[float]}
_cache: dict[str, dict[str, Any]] = {}


# Back-compat alias used by older imports / tests
def breathing_coefficient_from_ratio(smooth_ratio: float, symbol: str | None = None) -> float:
    return get_breathing_coefficient(smooth_ratio, symbol)


def _cache_key(symbol: str | None) -> str:
    can = normalize_canonical_symbol(symbol) or "ETHUSDT"
    return f"binance1h:{can}"


def _fetch_1h_klines(client: Any, symbol: str | None) -> list:
    """Prefer any client.fetch_klines(1h); always fall back to Binance public."""
    can = normalize_canonical_symbol(symbol) or "ETHUSDT"
    if client is not None and hasattr(client, "fetch_klines"):
        try:
            rows = client.fetch_klines(symbol=can, interval="1h", limit=KLINE_LIMIT)
            if rows:
                return list(rows)
        except Exception as e:
            logger.debug("client.fetch_klines 1h failed: %s", e)
    if hasattr(client, "get_klines"):
        try:
            rows = client.get_klines(symbol=can, interval="1h", limit=KLINE_LIMIT)
            if rows:
                return list(rows)
        except Exception as e:
            logger.debug("client.get_klines 1h failed: %s", e)
    try:
        return binance_public_klines(can, interval="1h", limit=KLINE_LIMIT)
    except Exception as e:
        logger.warning("Binance 1h klines fetch failed: %s", e)
        # Last-chance raw GET (tests may monkeypatch requests)
        try:
            resp = requests.get(
                BINANCE_FAPI_KLINES,
                params={"symbol": can, "interval": "1h", "limit": KLINE_LIMIT},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            return list(data) if isinstance(data, list) else []
        except Exception as e2:
            logger.warning("Binance 1h klines raw fetch failed: %s", e2)
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
    """Cached 1h ATR(14); refresh at most every REFRESH_SEC unless force."""
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
    """Return (atr_1h, refreshed). refreshed=True when a new fetch ran."""
    del exchange  # unused — always Binance public 1h
    key = _cache_key(symbol)
    now = time.time()
    with _lock:
        hit = _cache.get(key) or {}
        age = now - float(hit.get("fetched_at") or 0)
        if not force and float(hit.get("atr") or 0) > 0 and age < REFRESH_SEC:
            return float(hit["atr"]), False

    rows = _fetch_1h_klines(client, symbol)
    atr = compute_atr_1h_from_klines(rows)
    with _lock:
        prev = _cache.get(key) or {}
        if atr <= 0:
            return float(prev.get("atr") or 0), False
        _cache[key] = {
            "atr": atr,
            "fetched_at": now,
            "ratios": list(prev.get("ratios") or []),
        }
        return atr, True


def update_breathing_coefficient(
    *,
    initial_atr: float,
    atr_1h: float,
    ratio_history: list[float] | None = None,
    symbol: str | None = None,
) -> tuple[float, list[float], float]:
    """Return (coef, updated_ratios, smooth_ratio).

    Smooth the raw ratio first, then apply continuous trailDistanceMultiplier once.
    Empty history → cold-start ratio=1.0 (not a discrete ladder bucket).
    """
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
    """Pull 1h ATR and update supervisor.breathing_coefficient (+ ratio buffer).

    Ratio samples append only when ATR is freshly fetched (≤ every 5 min) or force.
    Soft ticks reuse the last smoothed coefficient without expanding the SMA window.
    0 samples → cold-start continuous formula at ratio=1.0.
    """
    from app.core.breathing_profile import cold_start_multiplier, profile_for_symbol
    from app.core.breathing_stop import get_breathing_coefficient as _coef_fn

    init = float(getattr(supervisor, "initial_atr", 0) or 0)
    client = getattr(supervisor, "client", None)
    ex = getattr(supervisor, "exchange_id", None) or getattr(client, "exchange_id", None)
    sym = (
        getattr(supervisor, "canonical_symbol", None)
        or getattr(supervisor, "symbol", None)
        or "ETHUSDT"
    )
    atr_1h, refreshed = get_atr_1h_with_meta(
        client=client, exchange=ex, symbol=sym, force=force,
    )
    hist = list(getattr(supervisor, "breath_ratio_history", None) or [])
    p = profile_for_symbol(sym)
    if refreshed or force or not hist:
        if init > 0 and atr_1h > 0:
            coef, hist, smooth = update_breathing_coefficient(
                initial_atr=init, atr_1h=atr_1h, ratio_history=hist, symbol=sym,
            )
        else:
            smooth = 1.0
            coef = cold_start_multiplier(p)
    else:
        if init > 0 and atr_1h > 0 and hist:
            smooth = sum(hist) / len(hist)
            coef = _coef_fn(smooth, sym)
        else:
            smooth = float(getattr(supervisor, "breath_smooth_ratio", 1.0) or 1.0)
            coef = cold_start_multiplier(p) if not hist else float(
                getattr(supervisor, "breathing_coefficient", 0) or cold_start_multiplier(p)
            )
    supervisor.atr_1h = atr_1h
    supervisor.breath_ratio_history = hist
    supervisor.breathing_coefficient = coef
    supervisor.breath_smooth_ratio = smooth
    return {
        "atr_1h": atr_1h,
        "initial_atr": init,
        "smooth_ratio": smooth,
        "breathing_coefficient": coef,
        "refreshed": bool(refreshed or force),
        "symbol": sym,
    }


def reset_1h_atr_cache_for_tests() -> None:
    with _lock:
        _cache.clear()
