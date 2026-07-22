"""Per-symbol breathing profiles — continuous trailDistanceMultiplier (final spec).

ETH/XAU share ratioFloor/ratioCeiling; only minMult/maxMult differ.
XAU tightness is entirely in min/max — no extra trail_tighten layer.
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
)

XAU_PROFILE = BreathingProfile(
    symbol_tag="XAU",
    initial_sl_atr=1.5,
    stop_order_buffer=0.5,
    early_breakeven_atr=0.3,
    step_trigger_atr=0.4,
    step_advance_atr=0.35,
    phase2_trigger_atr=3.0,
    coef_min=0.8,
    coef_max=1.8,
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
        "step_trigger_atr": profile.step_trigger_atr,
        "step_advance_atr": profile.step_advance_atr,
        "phase2_trigger_atr": profile.phase2_trigger_atr,
        "coef_min": profile.coef_min,
        "coef_max": profile.coef_max,
        "ratio_floor": profile.ratio_floor,
        "ratio_ceiling": profile.ratio_ceiling,
        "trail_tighten": 1.0,  # removed — always 1.0 (tightness in min/max)
    }
