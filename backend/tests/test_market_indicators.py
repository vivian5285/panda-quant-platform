"""Unit tests for 90m synthesis + Wilder ATR/ADX."""

from app.core.market_indicators import (
    BAR_MS_30M,
    BAR_MS_90M,
    aggregate_30m_to_90m,
    compute_atr_adx_from_30m,
    wilder_adx,
    wilder_atr,
)


def _mk_30m(start_ms: int, n: int, *, base_price: float = 100.0, step: float = 1.0):
    """Synthetic rising 30m candles."""
    out = []
    for i in range(n):
        ot = start_ms + i * BAR_MS_30M
        o = base_price + i * step
        c = o + step * 0.5
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5
        out.append([ot, o, h, l, c, 10.0])
    return out


def test_aggregate_three_30m_into_one_90m():
    # Align to a 90m boundary
    start = 0  # epoch
    candles = _mk_30m(start, 3, base_price=100, step=2)
    bars = aggregate_30m_to_90m(candles, now_ms=BAR_MS_90M)  # exactly closed
    assert len(bars) == 1
    b = bars[0]
    assert b["open_time"] == 0
    assert b["open"] == 100
    assert b["close"] == candles[-1][4]
    assert b["high"] == max(c[2] for c in candles)
    assert b["low"] == min(c[3] for c in candles)
    assert b["volume"] == 30.0


def test_incomplete_group_dropped():
    start = 0
    candles = _mk_30m(start, 2)  # only 2 of 3
    bars = aggregate_30m_to_90m(candles, now_ms=BAR_MS_90M)
    assert bars == []


def test_open_90m_bar_excluded_when_now_inside():
    start = 0
    candles = _mk_30m(start, 6)  # two full 90m groups if closed
    # Midway through second 90m bar (after 4th 30m = index 3.. still forming bar at 90m)
    now = BAR_MS_90M + BAR_MS_30M  # inside second bucket, first closed
    bars = aggregate_30m_to_90m(candles, now_ms=now)
    assert len(bars) == 1
    assert bars[0]["open_time"] == 0


def test_wilder_atr_known_path():
    # Flat then one wide bar — enough history for ATR(3)
    candles = []
    for i in range(10):
        candles.append({
            "open_time": float(i),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        })
    # Expand last bar
    candles[-1]["high"] = 110.0
    candles[-1]["low"] = 90.0
    atr = wilder_atr(candles, period=3)
    assert atr > 2.0  # TR of last ≈ 20 pulls ATR up from ~2


def test_wilder_adx_trending_nonzero():
    # Strong uptrend → ADX should be > 0 with enough bars
    candles = []
    px = 100.0
    for i in range(50):
        o, c = px, px + 2
        candles.append({
            "open_time": float(i * BAR_MS_90M),
            "open": o,
            "high": c + 0.5,
            "low": o - 0.2,
            "close": c,
            "volume": 1.0,
        })
        px = c
    adx = wilder_adx(candles, period=14)
    assert adx > 10.0


def test_compute_pipeline_needs_history():
    start = 0
    candles = _mk_30m(start, 100, base_price=1800, step=0.5)
    now = start + 100 * BAR_MS_30M
    out = compute_atr_adx_from_30m(candles, period=14, now_ms=now)
    assert out["bars_90"] >= 30
    assert out["atr"] > 0
    assert out["adx"] > 0
    assert out["bar_open_ms"] > 0


def test_native_4h_pipeline():
    from app.core.market_indicators import compute_atr_adx_from_klines

    bar_ms = 4 * 60 * 60 * 1000
    candles = []
    px = 1800.0
    for i in range(50):
        o, c = px, px + 2
        candles.append([i * bar_ms, o, c + 0.5, o - 0.2, c, 1.0])
        px = c
    now = 50 * bar_ms
    out = compute_atr_adx_from_klines(
        candles, period=14, now_ms=now, bar_minutes=240, synthesize_from_30m=False,
    )
    assert out["bar_count"] >= 40
    assert out["atr"] > 0
    assert out["adx"] > 0


def test_utc_epoch_90m_bucket_not_process_start():
    """Anchor is Unix-epoch floor — independent of process start / arbitrary offset."""
    from datetime import datetime, timezone

    from app.core.market_indicators import utc_90m_bucket_ms

    day0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    assert utc_90m_bucket_ms(day0) == day0
    assert utc_90m_bucket_ms(day0 + BAR_MS_30M) == day0
    assert utc_90m_bucket_ms(day0 + 2 * BAR_MS_30M) == day0
    assert utc_90m_bucket_ms(day0 + BAR_MS_90M) == day0 + BAR_MS_90M

    candles = _mk_30m(day0, 3, base_price=2000, step=1)
    bars = aggregate_30m_to_90m(candles, now_ms=day0 + BAR_MS_90M)
    assert len(bars) == 1
    assert bars[0]["open_time"] == float(day0)


def test_evaluate_atr_anomaly_and_invalid():
    from app.core.market_indicators import evaluate_atr_sanity

    assert evaluate_atr_sanity(0, [10] * 20)["error"] == "atr_invalid"
    bad = evaluate_atr_sanity(10, [100.0] * 50, lookback=50, floor_ratio=0.3)
    assert bad["ok"] is False and bad["error"] == "atr_anomaly"
    good = evaluate_atr_sanity(40, [100.0] * 50, lookback=50, floor_ratio=0.3)
    assert good["ok"] is True
