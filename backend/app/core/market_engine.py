"""VPS market engine — 30m→90m ATR(14)/ADX(14) cache (UTC epoch 90m buckets).

Breathing stop reads ATR/ADX only from here (never from TV webhook).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from app.config import get_settings
from app.core.market_indicators import compute_atr_adx_from_klines
from app.core.symbol_registry import (
    exchange_native_symbol,
    normalize_canonical_symbol,
)

logger = logging.getLogger(__name__)

BINANCE_FAPI_KLINES = "https://fapi.binance.com/fapi/v1/klines"

_lock = threading.RLock()
_cache: dict[str, dict[str, Any]] = {}


def _cache_key(exchange: str | None, symbol: str | None) -> str:
    ex = (exchange or "binance").strip().lower()
    if ex == "gateio":
        ex = "gate"
    can = normalize_canonical_symbol(symbol) or "ETHUSDT"
    return f"{ex}:{can}"


def binance_public_klines(
    symbol: str,
    interval: str = "30m",
    limit: int = 250,
) -> list[list]:
    """Public Binance USDT-M klines (no API key)."""
    can = normalize_canonical_symbol(symbol) or "ETHUSDT"
    native = exchange_native_symbol("binance", can)
    params = {"symbol": native, "interval": interval, "limit": int(limit)}
    resp = requests.get(BINANCE_FAPI_KLINES, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return []
    return data


def _fetch_via_client(client: Any, symbol: str | None, interval: str, limit: int) -> list:
    if client is None:
        return []
    if hasattr(client, "fetch_klines"):
        try:
            rows = client.fetch_klines(symbol=symbol, interval=interval, limit=limit)
            return list(rows or [])
        except Exception as exc:
            logger.warning(
                "[MarketEngine] client.fetch_klines failed (%s): %s",
                getattr(client, "exchange_id", type(client).__name__),
                exc,
            )
    return []


def fetch_strategy_klines(
    *,
    client: Any = None,
    exchange: str | None = None,
    symbol: str | None = None,
    limit: int | None = None,
) -> tuple[list, str]:
    """Return (klines, source). Prefer exchange client; fall back to Binance public."""
    settings = get_settings()
    interval = str(getattr(settings, "KLINE_BASE_INTERVAL", "30m") or "30m")
    lim = int(
        limit
        or getattr(settings, "KLINE_FETCH_LIMIT", 0)
        or getattr(settings, "KLINE_FETCH_LIMIT_30M", 250)
        or 250
    )
    ex = (exchange or getattr(client, "exchange_id", None) or "binance").strip().lower()
    if ex == "gateio":
        ex = "gate"
    can = normalize_canonical_symbol(
        symbol
        or getattr(client, "canonical_symbol", None)
        or getattr(client, "trading_symbol", None)
    ) or "ETHUSDT"

    rows = _fetch_via_client(client, symbol or can, interval, lim)
    if rows:
        return rows, f"{ex}"

    try:
        rows = binance_public_klines(can, interval=interval, limit=lim)
        if rows:
            if ex != "binance":
                logger.warning(
                    "[MarketEngine] %s klines failed → Binance public fallback for %s",
                    ex, can,
                )
            return rows, "binance_public"
    except Exception as exc:
        logger.warning("[MarketEngine] Binance public klines failed for %s: %s", can, exc)
    return [], "none"


# Compat alias
fetch_30m_klines = fetch_strategy_klines


def refresh_indicators(
    *,
    client: Any = None,
    exchange: str | None = None,
    symbol: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Fetch/compute ATR+ADX; update cache. Returns snapshot dict."""
    settings = get_settings()
    period = int(getattr(settings, "ATR_ADX_PERIOD", 14) or 14)
    bar_minutes = int(getattr(settings, "STRATEGY_BAR_MINUTES", 90) or 90)
    ex = (exchange or getattr(client, "exchange_id", None) or "binance").strip().lower()
    if ex == "gateio":
        ex = "gate"
    can = normalize_canonical_symbol(
        symbol
        or getattr(client, "canonical_symbol", None)
        or getattr(client, "trading_symbol", None)
    ) or "ETHUSDT"
    key = _cache_key(ex, can)
    now_ms = time.time() * 1000.0

    with _lock:
        prev = dict(_cache.get(key) or {})
        if (
            not force
            and float(prev.get("atr") or 0) > 0
            and float(prev.get("bar_open_ms") or 0) > 0
        ):
            bar_ms = bar_minutes * 60 * 1000
            next_bar_close_ms = float(prev["bar_open_ms"]) + 2 * bar_ms
            if now_ms < next_bar_close_ms:
                return dict(prev)

    rows, source = fetch_strategy_klines(
        client=client, exchange=ex, symbol=can,
    )
    synth = bar_minutes == 90
    computed = compute_atr_adx_from_klines(
        rows,
        period=period,
        now_ms=now_ms,
        bar_minutes=bar_minutes,
        synthesize_from_30m=synth,
    )
    atr_series = list(computed.get("atr_series") or [])
    snap = {
        "atr": float(computed.get("atr") or 0),
        "adx": float(computed.get("adx") or 0),
        "atr_series": atr_series,
        "bar_open_ms": float(computed.get("bar_open_ms") or 0),
        "bars_90": int(computed.get("bar_count") or computed.get("bars_90") or 0),
        "bar_count": int(computed.get("bar_count") or computed.get("bars_90") or 0),
        "source": source,
        "exchange": ex,
        "symbol": can,
        "updated_at": time.time(),
        "period": period,
        "bar_minutes": bar_minutes,
    }
    if snap["atr"] <= 0 and prev.get("atr", 0) > 0:
        snap["atr"] = float(prev["atr"])
        snap["adx"] = float(prev.get("adx") or snap["adx"])
        snap["bar_open_ms"] = float(prev.get("bar_open_ms") or snap["bar_open_ms"])
        if prev.get("atr_series"):
            snap["atr_series"] = list(prev.get("atr_series") or [])
        snap["stale"] = True
    else:
        snap["stale"] = False

    with _lock:
        _cache[key] = snap
    return dict(snap)


def ensure_fresh(
    *,
    client: Any = None,
    exchange: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    return refresh_indicators(
        client=client, exchange=exchange, symbol=symbol, force=False,
    )


def force_refresh(
    *,
    client: Any = None,
    exchange: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    return refresh_indicators(
        client=client, exchange=exchange, symbol=symbol, force=True,
    )


def get_cached(
    *,
    exchange: str | None = None,
    symbol: str | None = None,
    client: Any = None,
) -> dict[str, Any]:
    ex = exchange or getattr(client, "exchange_id", None)
    sym = symbol or getattr(client, "canonical_symbol", None) or getattr(client, "trading_symbol", None)
    key = _cache_key(ex, sym)
    with _lock:
        return dict(_cache.get(key) or {})


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def implied_atr_from_tv_stop(
    entry: float,
    stop_loss: float,
    *,
    initial_sl_atr: float = 1.5,
) -> float:
    e = float(entry or 0)
    sl = float(stop_loss or 0)
    mult = float(initial_sl_atr or 1.5)
    if e <= 0 or sl <= 0 or mult <= 0:
        return 0.0
    return abs(e - sl) / mult


def atr_mismatch_ratio(vps_atr: float, implied_atr: float) -> float:
    a = float(vps_atr or 0)
    b = float(implied_atr or 0)
    if a <= 0 or b <= 0:
        return 0.0
    return abs(a - b) / a
