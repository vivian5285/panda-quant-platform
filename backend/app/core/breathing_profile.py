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
    # Deprecated: live first-move uses fill±tp1_distance×(0.85/1.00) (whitepaper v3).
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
    early_breakeven_atr=0.5,  # activate → entry±0.5ATR
    step_trigger_atr=0.50,  # mid-tier whitepaper default
    step_advance_atr=0.35,
    phase2_trigger_atr=3.0,
    coef_min=2.0,
    coef_max=2.5,
    chart_tf_min=90.0,
    stagnant_window_min=90.0,
)

XAU_PROFILE = BreathingProfile(
    symbol_tag="XAU",
    initial_sl_atr=1.5,
    stop_order_buffer=0.5,
    early_breakeven_atr=0.5,
    step_trigger_atr=0.40,
    step_advance_atr=0.30,
    phase2_trigger_atr=3.0,
    coef_min=1.8,
    coef_max=2.2,
    chart_tf_min=45.0,  # actual TV chart
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


# §14 purge: dynamic 0.50~0.85 arm removed — whitepaper fixed first-open 0.85
RADAR_ARM_RATIO_MIN = 0.85
RADAR_ARM_RATIO_MAX = 0.85


def radar_start_ratio(smooth_ratio: float, profile: BreathingProfile | None = None) -> float:
    """Fixed first-open arm ratio 0.85 (whitepaper v3). ``smooth_ratio`` ignored."""
    del smooth_ratio, profile
    from app.core.trend_tier_params import RADAR_ARM_TP1_PCT

    return float(RADAR_ARM_TP1_PCT)


def radar_arm_distance(initial_atr: float, smooth_ratio: float, profile: BreathingProfile | None = None) -> float:
    """ATR-span fallback at fixed 0.85×TP1_atr×ATR (compat only).

    LIVE arm: ``trend_tier_params.radar_arm_trigger_price`` (fill±tv tp1_distance).
    """
    p = profile or ETH_PROFILE
    atr = float(initial_atr or 0)
    if atr <= 0:
        return 0.0
    del smooth_ratio
    return float(p.tp1_atr) * atr * radar_start_ratio(1.0, p)


def effective_radar_arm_distance(
    initial_atr: float,
    smooth_ratio: float,
    profile: BreathingProfile | None = None,
    *,
    arm_tp1_pct: float | None = None,
    step_trigger_atr: float | None = None,
) -> float:
    """Arm distance when ``arm_tp1_pct`` given; else fixed 0.85 ATR-span fallback."""
    from app.core.trend_tier_params import RADAR_ARM_TP1_PCT

    p = profile or ETH_PROFILE
    atr = float(initial_atr or 0)
    if atr <= 0:
        return 0.0
    if arm_tp1_pct is not None:
        try:
            pct = float(arm_tp1_pct)
        except (TypeError, ValueError):
            pct = float(RADAR_ARM_TP1_PCT)
        if pct <= 0:
            pct = float(RADAR_ARM_TP1_PCT)
        trig = float(
            step_trigger_atr
            if step_trigger_atr is not None
            else p.step_trigger_atr
        )
        return max(float(p.tp1_atr) * atr * pct, trig * atr)
    del smooth_ratio
    return radar_arm_distance(atr, 1.0, p)


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


def resolve_coef(
    coef: float | None,
    profile: BreathingProfile | None = None,
    *,
    coef_min: float | None = None,
    coef_max: float | None = None,
) -> float:
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


def profile_as_dict(profile: BreathingProfile) -> dict[str, Any]:
    return {
        "symbol_tag": profile.symbol_tag,
        "initial_sl_atr": profile.initial_sl_atr,
        "stop_order_buffer": profile.stop_order_buffer,
        "early_breakeven_atr": profile.early_breakeven_atr,
        "step_trigger_atr": profile.step_trigger_atr,
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
        "radar_arm": "fill±tp1_distance×(0.85首次/1.00重入)（白皮书v3）",
        "trail_tighten": 1.0,  # removed — always 1.0 (tightness in min/max)
    }
