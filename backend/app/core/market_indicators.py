"""Pure OHLCV indicators for breathing-stop market engine.

Strategy bar = 90m (exchanges lack native 90m → aggregate 3×30m).
ATR(14) / ADX(14) use Wilder's smoothing.

90m time anchor (must match TradingView custom 90m):
  bucket_open_ms = (open_time_ms // 5_400_000) * 5_400_000
  i.e. Unix-epoch UTC floors of 90 minutes — NOT "from process start".
  Because 24h/90m = 16 exactly, UTC midnight is always a bucket boundary.
"""

from __future__ import annotations

import statistics
from typing import Any, Sequence

DEFAULT_PERIOD = 14
BAR_MS_30M = 30 * 60 * 1000
BAR_MS_90M = 90 * 60 * 1000


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v if v is not None else default)
    except (TypeError, ValueError):
        return float(default)


def normalize_candle(row: Sequence | dict) -> dict[str, float]:
    """Normalize exchange kline row or dict to {open_time, open, high, low, close, volume}."""
    if isinstance(row, dict):
        ot = row.get("open_time") or row.get("t") or row.get("ts") or row.get(0) or 0
        return {
            "open_time": float(ot),
            "open": _f(row.get("open", row.get("o"))),
            "high": _f(row.get("high", row.get("h"))),
            "low": _f(row.get("low", row.get("l"))),
            "close": _f(row.get("close", row.get("c"))),
            "volume": _f(row.get("volume", row.get("v", row.get("vol")))),
        }
    # Binance-style list: [open_time, o, h, l, c, volume, ...]
    return {
        "open_time": float(row[0]),
        "open": _f(row[1]),
        "high": _f(row[2]),
        "low": _f(row[3]),
        "close": _f(row[4]),
        "volume": _f(row[5] if len(row) > 5 else 0),
    }


def utc_90m_bucket_ms(open_time_ms: float | int, bar_ms: int = BAR_MS_90M) -> int:
    """TradingView-compatible 90m bucket open = UTC Unix epoch floor."""
    ot = int(open_time_ms)
    bm = int(bar_ms)
    return (ot // bm) * bm


def aggregate_30m_to_90m(
    candles_30m: Sequence[Sequence | dict],
    *,
    now_ms: float | None = None,
    bar_ms: int = BAR_MS_90M,
    base_ms: int = BAR_MS_30M,
) -> list[dict[str, float]]:
    """Merge consecutive 30m candles into closed 90m bars (UTC epoch aligned).

    Anchor: ``bucket = (open_time_ms // 5_400_000) * 5_400_000`` (same for every
    exchange / process restart). Incomplete groups (< 3 base bars) and the
    still-open 90m bucket are dropped when now_ms is provided.
    """
    if not candles_30m:
        return []

    bars = [normalize_candle(c) for c in candles_30m]
    bars.sort(key=lambda b: b["open_time"])

    groups: dict[int, list[dict[str, float]]] = {}
    for b in bars:
        bucket = utc_90m_bucket_ms(b["open_time"], bar_ms)
        groups.setdefault(bucket, []).append(b)

    out: list[dict[str, float]] = []
    expected = max(1, int(bar_ms // base_ms))
    for bucket in sorted(groups.keys()):
        chunk = groups[bucket]
        chunk.sort(key=lambda b: b["open_time"])
        if len(chunk) < expected:
            continue
        # Use first `expected` bars in the bucket (ignore extras if any)
        chunk = chunk[:expected]
        close_ms = bucket + bar_ms
        if now_ms is not None and float(now_ms) < close_ms:
            continue  # bar not closed yet
        out.append({
            "open_time": float(bucket),
            "open": chunk[0]["open"],
            "high": max(x["high"] for x in chunk),
            "low": min(x["low"] for x in chunk),
            "close": chunk[-1]["close"],
            "volume": sum(x["volume"] for x in chunk),
        })
    return out


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def wilder_atr_series(
    candles: Sequence[dict[str, float]],
    period: int = DEFAULT_PERIOD,
) -> list[float]:
    """Running Wilder ATR after each bar once warm (length = len(candles)-period)."""
    n = int(period or DEFAULT_PERIOD)
    if n < 1 or len(candles) < n + 1:
        return []
    trs: list[float] = []
    for i in range(1, len(candles)):
        trs.append(true_range(
            candles[i]["high"], candles[i]["low"], candles[i - 1]["close"],
        ))
    if len(trs) < n:
        return []
    atr = sum(trs[:n]) / n
    series = [float(atr)]
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
        series.append(float(atr))
    return series


def wilder_atr(
    candles: Sequence[dict[str, float]],
    period: int = DEFAULT_PERIOD,
) -> float:
    """Wilder ATR on closed OHLCV bars. Returns 0 if insufficient history."""
    series = wilder_atr_series(candles, period)
    return float(series[-1]) if series else 0.0


def evaluate_atr_sanity(
    atr: float,
    atr_series: Sequence[float] | None = None,
    *,
    lookback: int = 50,
    floor_ratio: float = 0.30,
    min_samples: int = 10,
) -> dict[str, Any]:
    """Open-time ATR guard: reject if ATR≤0 or << recent median (not a permanent pause)."""
    atr_f = float(atr or 0)
    meta: dict[str, Any] = {
        "atr": round(atr_f, 6),
        "atr_median": None,
        "atr_floor_ratio": float(floor_ratio),
        "lookback": int(lookback),
    }
    if atr_f <= 0:
        meta["ok"] = False
        meta["error"] = "atr_invalid"
        return meta

    series = [float(x) for x in (atr_series or []) if float(x or 0) > 0]
    window = series[-int(lookback) :] if series else []
    meta["atr_series_len"] = len(series)
    meta["atr_window_len"] = len(window)
    if len(window) < int(min_samples):
        # Not enough history for median — allow if atr>0 (warmup)
        meta["ok"] = True
        meta["median_check"] = "skipped_insufficient_history"
        return meta

    med = float(statistics.median(window))
    meta["atr_median"] = round(med, 6)
    floor = med * float(floor_ratio)
    meta["atr_floor"] = round(floor, 6)
    if atr_f < floor - 1e-12:
        meta["ok"] = False
        meta["error"] = "atr_anomaly"
        meta["median_check"] = "failed"
        return meta
    meta["ok"] = True
    meta["median_check"] = "passed"
    return meta


def wilder_adx(
    candles: Sequence[dict[str, float]],
    period: int = DEFAULT_PERIOD,
) -> float:
    """Wilder ADX(period). Needs roughly 2*period+1 bars; returns 0 if short."""
    n = int(period or DEFAULT_PERIOD)
    if n < 1 or len(candles) < 2 * n + 1:
        return 0.0

    plus_dm: list[float] = []
    minus_dm: list[float] = []
    trs: list[float] = []
    for i in range(1, len(candles)):
        up = candles[i]["high"] - candles[i - 1]["high"]
        down = candles[i - 1]["low"] - candles[i]["low"]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(true_range(
            candles[i]["high"], candles[i]["low"], candles[i - 1]["close"],
        ))

    if len(trs) < 2 * n:
        return 0.0

    atr = sum(trs[:n]) / n
    sm_plus = sum(plus_dm[:n]) / n
    sm_minus = sum(minus_dm[:n]) / n

    dx_list: list[float] = []

    def _dx(atr_v: float, p: float, m: float) -> float:
        if atr_v <= 0:
            return 0.0
        di_p = 100.0 * p / atr_v
        di_m = 100.0 * m / atr_v
        s = di_p + di_m
        if s <= 0:
            return 0.0
        return 100.0 * abs(di_p - di_m) / s

    dx_list.append(_dx(atr, sm_plus, sm_minus))

    for i in range(n, len(trs)):
        atr = (atr * (n - 1) + trs[i]) / n
        sm_plus = (sm_plus * (n - 1) + plus_dm[i]) / n
        sm_minus = (sm_minus * (n - 1) + minus_dm[i]) / n
        dx_list.append(_dx(atr, sm_plus, sm_minus))

    if len(dx_list) < n:
        return 0.0
    adx = sum(dx_list[:n]) / n
    for dx in dx_list[n:]:
        adx = (adx * (n - 1) + dx) / n
    return float(adx)


def compute_atr_adx_from_30m(
    candles_30m: Sequence[Sequence | dict],
    *,
    period: int = DEFAULT_PERIOD,
    now_ms: float | None = None,
) -> dict[str, Any]:
    """Legacy pipeline: 30m → closed 90m → ATR/ADX (+ ATR series for sanity)."""
    bars_90 = aggregate_30m_to_90m(candles_30m, now_ms=now_ms)
    atr_series = wilder_atr_series(bars_90, period)
    atr = float(atr_series[-1]) if atr_series else 0.0
    adx = wilder_adx(bars_90, period)
    last_bar = bars_90[-1] if bars_90 else None
    return {
        "atr": atr,
        "adx": adx,
        "atr_series": atr_series,
        "bars_90": len(bars_90),
        "bar_count": len(bars_90),
        "bar_open_ms": float(last_bar["open_time"]) if last_bar else 0.0,
        "bars": bars_90,
    }


def closed_native_bars(
    candles: Sequence[Sequence | dict],
    *,
    bar_ms: int,
    now_ms: float | None = None,
) -> list[dict[str, float]]:
    """Normalize klines and drop the still-open bar."""
    if not candles:
        return []
    bars = [normalize_candle(c) for c in candles]
    bars.sort(key=lambda b: b["open_time"])
    if now_ms is None:
        return bars
    out = []
    for b in bars:
        close_ms = float(b["open_time"]) + float(bar_ms)
        if float(now_ms) >= close_ms:
            out.append(b)
    return out


def compute_atr_adx_from_klines(
    candles: Sequence[Sequence | dict],
    *,
    period: int = DEFAULT_PERIOD,
    now_ms: float | None = None,
    bar_minutes: int = 240,
    synthesize_from_30m: bool = False,
) -> dict[str, Any]:
    """ATR/ADX on strategy bars. Native TF or 30m→90m synth."""
    if synthesize_from_30m or int(bar_minutes) == 90:
        return compute_atr_adx_from_30m(candles, period=period, now_ms=now_ms)
    bar_ms = int(bar_minutes) * 60 * 1000
    bars = closed_native_bars(candles, bar_ms=bar_ms, now_ms=now_ms)
    atr_series = wilder_atr_series(bars, period)
    atr = float(atr_series[-1]) if atr_series else 0.0
    adx = wilder_adx(bars, period)
    last_bar = bars[-1] if bars else None
    return {
        "atr": atr,
        "adx": adx,
        "atr_series": atr_series,
        "bars_90": len(bars),  # compat key
        "bar_count": len(bars),
        "bar_open_ms": float(last_bar["open_time"]) if last_bar else 0.0,
        "bars": bars,
    }
