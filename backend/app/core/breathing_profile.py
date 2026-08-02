"""Per-symbol breathing profiles — continuous trailDistanceMultiplier (final spec).

ETH/XAU/BNB share ratioFloor/ratioCeiling; only minMult/maxMult differ.
BNB is mid-tier volatility (between ETH and XAU).
XAU min/max were retuned after production backtest.

TP1 + TP2 always hung as limit orders. TP3 NEVER.
TP3 residual 70% is radar-only (no TP3 limit order ever).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.symbol_registry import (
    CANONICAL_BNB,
    CANONICAL_ETH,
    CANONICAL_XAU,
    normalize_canonical_symbol,
)

# Shared continuous-interpolation bounds (both symbols)
RATIO_FLOOR = 0.6
RATIO_CEILING = 2.2
# Cold-start assumption before any live ATR sample: market ≈ open ATR
COLD_START_RATIO = 1.0


@dataclass(frozen=True)
class BreathingProfile:
    symbol_tag: str  # ETH | XAU | BNB
    initial_sl_atr: float = 1.5
    stop_order_buffer: float = 0.3
    # Radar arm: absolute price anchor (Spec §6.1)
    # step_* fields: used for Phase-1 step tracking only (before arm)
    step_trigger_atr: float = 0.50
    step_advance_atr: float = 0.35
    tp1_atr: float = 1.35  # TP1 distance = 1.35 × initial_atr (profile reference only)
    # Continuous trailDistanceMultiplier range (= breathing_coefficient)
    coef_min: float = 1.2
    coef_max: float = 2.5
    ratio_floor: float = RATIO_FLOOR
    ratio_ceiling: float = RATIO_CEILING
    chart_tf_min: float = 90.0
    stagnant_window_min: float = 90.0


ETH_PROFILE = BreathingProfile(
    symbol_tag="ETH",
    initial_sl_atr=1.5,
    stop_order_buffer=0.3,
    step_trigger_atr=0.50,
    step_advance_atr=0.35,
    tp1_atr=1.35,
    coef_min=2.0,
    coef_max=2.5,
    chart_tf_min=90.0,
    stagnant_window_min=90.0,
)

XAU_PROFILE = BreathingProfile(
    symbol_tag="XAU",
    initial_sl_atr=1.5,
    stop_order_buffer=0.5,
    step_trigger_atr=0.40,
    step_advance_atr=0.30,
    tp1_atr=1.35,
    coef_min=1.5,
    coef_max=2.0,
    chart_tf_min=45.0,
    stagnant_window_min=60.0,
)

# BNBUSDT — volatility between ETH and XAU
BNB_PROFILE = BreathingProfile(
    symbol_tag="BNB",
    initial_sl_atr=1.5,  # unified: spec requires 1.5 for all symbols
    stop_order_buffer=0.3,
    step_trigger_atr=0.45,
    step_advance_atr=0.30,
    tp1_atr=1.35,
    coef_min=1.6,
    coef_max=2.2,
    chart_tf_min=60.0,
    stagnant_window_min=60.0,
)

_PROFILES: dict[str, BreathingProfile] = {
    CANONICAL_ETH: ETH_PROFILE,
    CANONICAL_XAU: XAU_PROFILE,
    CANONICAL_BNB: BNB_PROFILE,
}


def profile_for_symbol(symbol: str | None = None) -> BreathingProfile:
    can = normalize_canonical_symbol(symbol) or CANONICAL_ETH
    return _PROFILES.get(can, ETH_PROFILE)


def symbol_tag(symbol: str | None = None) -> str:
    return profile_for_symbol(symbol).symbol_tag


def trail_distance_multiplier(
    ratio: float,
    profile: BreathingProfile | None = None,
    *,
    coef_min: float | None = None,
    coef_max: float | None = None,
) -> float:
    """Continuous linear interpolation — no discrete ladder jumps.

    ratio = smoothed(realtime_atr / initial_atr)
    Optional ``coef_min``/``coef_max`` override profile bands (smart-reentry tiers).
    """
    p = profile or ETH_PROFILE
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        r = COLD_START_RATIO
    if r != r:  # NaN
        r = COLD_START_RATIO
    lo, hi = float(p.ratio_floor), float(p.ratio_ceiling)
    mn = float(coef_min if coef_min is not None else p.coef_min)
    mx = float(coef_max if coef_max is not None else p.coef_max)
    if r <= lo:
        return mn
    if r >= hi:
        return mx
    span = hi - lo
    if span <= 0:
        return mn
    return mn + (mx - mn) * (r - lo) / span


def cold_start_multiplier(profile: BreathingProfile | None = None) -> float:
    """0 samples → ratio=1.0 into the continuous formula."""
    return trail_distance_multiplier(COLD_START_RATIO, profile)


def get_breathing_coefficient_for_profile(
    smooth_ratio: float,
    profile: BreathingProfile | None = None,
) -> float:
    """Alias: breathing_coefficient == trailDistanceMultiplier(smoothedRatio)."""
    p = profile or ETH_PROFILE
    if smooth_ratio is None:
        return cold_start_multiplier(p)
    try:
        r = float(smooth_ratio)
    except (TypeError, ValueError):
        return cold_start_multiplier(p)
    if r <= 0:
        return cold_start_multiplier(p)
    return trail_distance_multiplier(r, p)


def resolve_coef(
    coef: float | None,
    profile: BreathingProfile | None = None,
    *,
    coef_min: float | None = None,
    coef_max: float | None = None,
) -> float:
    """Resolve breathing coefficient with bounds clamping."""
    p = profile or ETH_PROFILE
    mn = float(coef_min if coef_min is not None else p.coef_min)
    mx = float(coef_max if coef_max is not None else p.coef_max)
    if mx < mn:
        mx = mn
    if coef is None:
        mid = cold_start_multiplier(p)
        return max(mn, min(mx, mid))
    try:
        c = float(coef)
    except (TypeError, ValueError):
        mid = cold_start_multiplier(p)
        return max(mn, min(mx, mid))
    if c <= 0:
        mid = cold_start_multiplier(p)
        return max(mn, min(mx, mid))
    return max(mn, min(mx, c))


def stagnant_breath_samples(profile: BreathingProfile | None = None) -> int:
    """5-min breath samples needed for stagnant-radar review (ETH≈18 / XAU≈12)."""
    p = profile or ETH_PROFILE
    window = float(p.stagnant_window_min or 0)
    if window <= 0:
        return 1
    return max(1, int(round(window / 5.0)))


def profile_as_dict(profile: BreathingProfile) -> dict[str, Any]:
    return {
        "symbol_tag": profile.symbol_tag,
        "initial_sl_atr": profile.initial_sl_atr,
        "stop_order_buffer": profile.stop_order_buffer,
        "step_trigger_atr": profile.step_trigger_atr,
        "step_advance_atr": profile.step_advance_atr,
        "tp1_atr": profile.tp1_atr,
        "coef_min": profile.coef_min,
        "coef_max": profile.coef_max,
        "ratio_floor": profile.ratio_floor,
        "ratio_ceiling": profile.ratio_ceiling,
        "chart_tf_min": profile.chart_tf_min,
        "stagnant_window_min": profile.stagnant_window_min,
        "stagnant_breath_samples": stagnant_breath_samples(profile),
        "radar_arm": "absolute_price_anchor (Spec §6.1): (TP1+TP2)/2 first, TP2 reentry",
        "activate_be": "fee+tick breakeven",
        "tp3": "never hung as limit — radar-only residual",
    }
