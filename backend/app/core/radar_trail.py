"""Radar breakeven trailing — regime slack so normal pullbacks do not stop out early."""

from __future__ import annotations

from app.core.symbol_precision import round_price

# Min trail width as fraction of entry→TP1 (avoids ATR-only tight stops on ETH)
RADAR_MIN_TRAIL_TP1_FRAC = 0.22
FEE_BUFFER_PCT = 0.0015
# Breakeven floor slack (ATR) — wider before TP1, tighter after TP1 lock-in
RADAR_BREAKEVEN_ATR_BEFORE_TP1 = 0.55
RADAR_BREAKEVEN_ATR_AFTER_TP1 = 0.25
# Arm STOP only after TP1 fill, or path progress ≥ this (late trend lock)
RADAR_PRE_TP1_ARM_PROGRESS = 0.96
RADAR_STARTUP_PROFIT_PROGRESS = 0.96

# Looser activation path + wider ATR trail vs legacy tight defaults
REGIME_RADAR: dict[int, dict[str, float]] = {
    1: {"activation": 0.85, "trail_offset": 0.75},
    2: {"activation": 0.88, "trail_offset": 1.00},
    3: {"activation": 0.90, "trail_offset": 1.35},
    4: {"activation": 0.95, "trail_offset": 1.80},
}


def merge_regime_radar(base: dict[int, dict]) -> dict[int, dict]:
    """Overlay looser radar params onto margin/ratios regime_settings."""
    merged: dict[int, dict] = {}
    for r, cfg in base.items():
        row = dict(cfg)
        row.update(REGIME_RADAR.get(int(r), {}))
        merged[int(r)] = row
    return merged


def tp1_distance(entry: float, tv_tps: list, atr: float) -> float:
    if tv_tps and float(tv_tps[0] or 0) > 0:
        return abs(float(tv_tps[0]) - float(entry))
    return max(float(atr or 0) * 1.5, 1.0)


def trail_distance(atr: float, trail_mult: float, tp1_dist: float) -> float:
    atr_dist = max(float(atr or 0), 0.0) * max(float(trail_mult or 0), 0.0)
    min_dist = max(float(tp1_dist or 0) * RADAR_MIN_TRAIL_TP1_FRAC, 0.0)
    return max(atr_dist, min_dist)


def tp1_consumed(consumed_tp_levels: list | None) -> bool:
    return 1 in (consumed_tp_levels or [])


def radar_may_arm(
    *,
    consumed_tp_levels: list | None,
    progress: float,
    activation_ratio: float,
    radar_active: bool = False,
) -> bool:
    """
    When to place/move breakeven radar STOP:
    - TP1 filled (primary — strategy has room to breathe until then)
    - already armed and trailing
    - or very late path progress (≥96%) on strong trend
    """
    if radar_active:
        return True
    if tp1_consumed(consumed_tp_levels):
        return True
    threshold = max(float(activation_ratio or 0), RADAR_PRE_TP1_ARM_PROGRESS)
    return float(progress or 0) >= threshold


def breakeven_floor(
    entry: float,
    side: str | None,
    atr: float,
    *,
    consumed_tp_levels: list | None = None,
) -> float:
    fee = float(entry) * FEE_BUFFER_PCT
    atr_mult = (
        RADAR_BREAKEVEN_ATR_AFTER_TP1
        if tp1_consumed(consumed_tp_levels)
        else RADAR_BREAKEVEN_ATR_BEFORE_TP1
    )
    slack = max(fee, float(atr or 0) * atr_mult)
    if side == "LONG":
        return round_price(float(entry) + slack)
    if side == "SHORT":
        return round_price(float(entry) - slack)
    return round_price(float(entry))


STOP_MARKET_MIN_GAP_USD = 1.0
STOP_MARKET_MIN_GAP_PCT = 0.0008


def stop_market_min_gap(curr_px: float) -> float:
    if curr_px <= 0:
        return STOP_MARKET_MIN_GAP_USD
    return max(STOP_MARKET_MIN_GAP_USD, float(curr_px) * STOP_MARKET_MIN_GAP_PCT)


def clamp_stop_market_safe(sl: float, curr_px: float, side: str | None) -> float:
    """Keep STOP trigger strictly on the safe side of mark — avoids instant full close."""
    if sl <= 0 or curr_px <= 0:
        return sl
    gap = stop_market_min_gap(curr_px)
    if side == "LONG":
        return round_price(min(float(sl), float(curr_px) - gap))
    if side == "SHORT":
        return round_price(max(float(sl), float(curr_px) + gap))
    return round_price(float(sl))


def stop_would_trigger_immediately(sl: float, curr_px: float, side: str | None) -> bool:
    """True when a closePosition STOP would fire as soon as it hits the book."""
    if sl <= 0 or curr_px <= 0:
        return False
    safe = clamp_stop_market_safe(sl, curr_px, side)
    if side == "LONG":
        return safe < sl - 1e-9
    if side == "SHORT":
        return safe > sl + 1e-9
    return False


def compute_radar_sl(
    *,
    side: str | None,
    entry: float,
    best_price: float,
    atr: float,
    trail_mult: float,
    tp1_dist: float,
    consumed_tp_levels: list | None,
    clamp_fn,
) -> float:
    trail = trail_distance(atr, trail_mult, tp1_dist)
    floor = clamp_fn(
        breakeven_floor(entry, side, atr, consumed_tp_levels=consumed_tp_levels)
    )
    if side == "LONG":
        return round_price(max(float(best_price) - trail, floor))
    if side == "SHORT":
        return round_price(min(float(best_price) + trail, floor))
    return round_price(float(entry))
