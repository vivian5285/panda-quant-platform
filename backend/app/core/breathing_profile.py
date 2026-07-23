"""Per-symbol breathing profiles — continuous trailDistanceMultiplier (final spec).

ETH/XAU share ratioFloor/ratioCeiling; only minMult/maxMult differ.
XAU tightness is entirely in min/max — no extra trail_tighten layer.

XAU min/max were retuned after production backtest (continuous 0.8~1.8
underperformed old discrete×0.8); see backend/data/_xau_min_max_sensitivity.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.symbol_registry import (
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
    symbol_tag: str  # ETH | XAU
    initial_sl_atr: float = 1.5
    stop_order_buffer: float = 0.3
    early_breakeven_atr: float = 0.5
    # Deprecated: live first-move uses radar_arm_distance (TP1×50%~85%).
    # Kept only so historical backtest scripts can rebuild the old 0.75 gate.
    step_trigger_atr: float = 0.75
    step_advance_atr: float = 0.4
    phase2_trigger_atr: float = 3.0
    tp1_atr: float = 1.35
    tp1_floor_atr: float = 0.5
    tp2_atr: float = 2.5
    tp2_floor_atr: float = 1.5
    tp3_atr: float = 4.0
    # Continuous trailDistanceMultiplier range (= breathing_coefficient)
    coef_min: float = 1.2  # minMult
    coef_max: float = 2.5  # maxMult
    ratio_floor: float = RATIO_FLOOR
    ratio_ceiling: float = RATIO_CEILING
    # TV chart period (minutes) — signal rhythm for this symbol
    chart_tf_min: float = 90.0
    # Stagnant-radar review window (minutes); ETH=chart, XAU=45×~1.33≈60
    stagnant_window_min: float = 90.0


ETH_PROFILE = BreathingProfile(
    symbol_tag="ETH",
    initial_sl_atr=1.5,
    stop_order_buffer=0.3,
    early_breakeven_atr=0.5,
    step_trigger_atr=0.75,
    step_advance_atr=0.4,
    phase2_trigger_atr=3.0,
    coef_min=1.2,
    coef_max=2.5,
    chart_tf_min=90.0,
    stagnant_window_min=90.0,
)

XAU_PROFILE = BreathingProfile(
    symbol_tag="XAU",
    initial_sl_atr=1.5,
    stop_order_buffer=0.5,
    early_breakeven_atr=0.3,
    step_trigger_atr=0.4,
    step_advance_atr=0.35,
    phase2_trigger_atr=3.0,
    # Tuned after continuous-vs-discrete backtest: 0.8~1.8 was too loose
    # vs old discrete×0.8 effective (~0.4~1.04). 0.5~1.2 keeps continuous
    # smoothness while matching discrete PnL/PF on 1h history.
    coef_min=0.5,
    coef_max=1.2,
    chart_tf_min=45.0,  # actual TV chart (docs previously said 1h — wrong)
    stagnant_window_min=60.0,  # 45×~1.33 buffer ≈ one bar + slack
)

_PROFILES: dict[str, BreathingProfile] = {
    CANONICAL_ETH: ETH_PROFILE,
    CANONICAL_XAU: XAU_PROFILE,
}


def profile_for_symbol(symbol: str | None = None) -> BreathingProfile:
    can = normalize_canonical_symbol(symbol) or CANONICAL_ETH
    return _PROFILES.get(can, ETH_PROFILE)


def symbol_tag(symbol: str | None = None) -> str:
    return profile_for_symbol(symbol).symbol_tag


def trail_distance_multiplier(ratio: float, profile: BreathingProfile | None = None) -> float:
    """Continuous linear interpolation — no discrete ladder jumps.

    ratio = smoothed(realtime_atr / initial_atr)
    """
    p = profile or ETH_PROFILE
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        r = COLD_START_RATIO
    if r != r:  # NaN
        r = COLD_START_RATIO
    lo, hi = float(p.ratio_floor), float(p.ratio_ceiling)
    mn, mx = float(p.coef_min), float(p.coef_max)
    if r <= lo:
        return mn
    if r >= hi:
        return mx
    span = hi - lo
    if span <= 0:
        return mn
    return mn + (mx - mn) * (r - lo) / span


# Radar first-move arm ratio (replaces fixed 0.75×ATR). Same input as trailDistanceMultiplier.
RADAR_ARM_RATIO_MIN = 0.50  # weak trend / high vol → early arm
RADAR_ARM_RATIO_MAX = 0.85  # strong trend / calm → late arm


def radar_start_ratio(smooth_ratio: float, profile: BreathingProfile | None = None) -> float:
    """Dynamic radar first-move fraction of TP1 distance (1.35×ATR).

    Shares ``smoothed(realtime_atr/initial_atr)`` with trailDistanceMultiplier,
    but **inverse** maps: high vol (weak) → 50%, low vol (strong) → 85%.
    Replaces deleted fixed ``step_trigger_atr`` (0.75) first-move gate.
    """
    p = profile or ETH_PROFILE
    try:
        r = float(smooth_ratio)
    except (TypeError, ValueError):
        r = COLD_START_RATIO
    if r != r or r <= 0:
        r = COLD_START_RATIO
    lo, hi = float(p.ratio_floor), float(p.ratio_ceiling)
    if r <= lo:
        return float(RADAR_ARM_RATIO_MAX)
    if r >= hi:
        return float(RADAR_ARM_RATIO_MIN)
    span = hi - lo
    if span <= 0:
        return float(RADAR_ARM_RATIO_MAX)
    t = (r - lo) / span  # 0 at calm → 1 at volatile
    return float(RADAR_ARM_RATIO_MAX) - t * (
        float(RADAR_ARM_RATIO_MAX) - float(RADAR_ARM_RATIO_MIN)
    )


def radar_arm_distance(initial_atr: float, smooth_ratio: float, profile: BreathingProfile | None = None) -> float:
    """Favorable move needed before first radar step: TP1_dist × start_ratio."""
    p = profile or ETH_PROFILE
    atr = float(initial_atr or 0)
    if atr <= 0:
        return 0.0
    tp1_dist = float(p.tp1_atr) * atr
    return tp1_dist * radar_start_ratio(smooth_ratio, p)


def stagnant_breath_samples(profile: BreathingProfile | None = None) -> int:
    """5-min breath samples needed for stagnant-radar review (ETH≈18 / XAU≈12)."""
    p = profile or ETH_PROFILE
    window = float(p.stagnant_window_min or 0)
    if window <= 0:
        return 1
    return max(1, int(round(window / 5.0)))


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
    # Non-positive / missing treated as cold-start (conservative mid)
    if r <= 0:
        return cold_start_multiplier(p)
    return trail_distance_multiplier(r, p)


def resolve_coef(coef: float | None, profile: BreathingProfile | None = None) -> float:
    p = profile or ETH_PROFILE
    if coef is None:
        return cold_start_multiplier(p)
    try:
        c = float(coef)
    except (TypeError, ValueError):
        return cold_start_multiplier(p)
    if c <= 0:
        return cold_start_multiplier(p)
    return max(p.coef_min, min(p.coef_max, c))


def profile_as_dict(profile: BreathingProfile) -> dict[str, Any]:
    return {
        "symbol_tag": profile.symbol_tag,
        "initial_sl_atr": profile.initial_sl_atr,
        "stop_order_buffer": profile.stop_order_buffer,
        "early_breakeven_atr": profile.early_breakeven_atr,
        "step_advance_atr": profile.step_advance_atr,
        "phase2_trigger_atr": profile.phase2_trigger_atr,
        "tp1_atr": profile.tp1_atr,
        "coef_min": profile.coef_min,
        "coef_max": profile.coef_max,
        "ratio_floor": profile.ratio_floor,
        "ratio_ceiling": profile.ratio_ceiling,
        "chart_tf_min": profile.chart_tf_min,
        "stagnant_window_min": profile.stagnant_window_min,
        "stagnant_breath_samples": stagnant_breath_samples(profile),
        "radar_arm": "TP1×50%~85% (dynamic; replaces step_trigger)",
        "trail_tighten": 1.0,  # removed — always 1.0 (tightness in min/max)
        # legacy field retained for backtest rebuilds only
        "step_trigger_atr_legacy": profile.step_trigger_atr,
    }
