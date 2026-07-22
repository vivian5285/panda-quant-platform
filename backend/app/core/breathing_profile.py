"""Per-symbol breathing profiles — shared engine, config-layer differences.

ETH and XAU use the same execution path; only multipliers / buffers / coef ladders differ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.symbol_registry import (
    CANONICAL_ETH,
    CANONICAL_XAU,
    normalize_canonical_symbol,
)


@dataclass(frozen=True)
class BreathingProfile:
    symbol_tag: str  # ETH | XAU
    initial_sl_atr: float = 1.5
    stop_order_buffer: float = 0.3
    # Early lock to entry±1 tick when float ≥ this × ATR (0 = disabled)
    early_breakeven_atr: float = 0.5
    step_trigger_atr: float = 0.75
    step_advance_atr: float = 0.4
    phase2_trigger_atr: float = 3.0
    tp1_atr: float = 1.35
    tp1_floor_atr: float = 0.5
    tp2_atr: float = 2.5
    tp2_floor_atr: float = 1.5
    tp3_atr: float = 4.0
    # Phase-2 trail = initial_atr × coef × trail_tighten
    trail_tighten: float = 1.0
    coef_min: float = 0.7
    coef_max: float = 1.5
    # Ladder breakpoints for get_breathing_coefficient(ratio)
    # (upper_exclusive, value_or_None for linear segment)
    # Linear segment: (lo_ratio, hi_ratio, lo_coef, hi_coef)


ETH_PROFILE = BreathingProfile(
    symbol_tag="ETH",
    initial_sl_atr=1.5,
    stop_order_buffer=0.3,
    early_breakeven_atr=0.5,
    step_trigger_atr=0.75,
    step_advance_atr=0.4,
    phase2_trigger_atr=3.0,
    trail_tighten=1.0,
    coef_min=0.7,
    coef_max=1.5,
)

XAU_PROFILE = BreathingProfile(
    symbol_tag="XAU",
    initial_sl_atr=1.5,
    stop_order_buffer=0.5,
    early_breakeven_atr=0.3,
    step_trigger_atr=0.4,
    step_advance_atr=0.35,
    phase2_trigger_atr=3.0,
    trail_tighten=0.8,
    coef_min=0.5,
    coef_max=1.3,
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


def get_breathing_coefficient_for_profile(
    smooth_ratio: float,
    profile: BreathingProfile | None = None,
) -> float:
    """Map smoothed (atr_1h / initial_atr) → breathing coefficient for this profile."""
    p = profile or ETH_PROFILE
    r = float(smooth_ratio or 0)
    if r <= 0:
        return 1.0 if p.symbol_tag == "ETH" else 0.9

    if p.symbol_tag == "XAU":
        # 0.5 / 0.7 / 0.9 / 1.0~1.2 / 1.3
        if r < 0.7:
            return 0.5
        if r < 1.0:
            return 0.7
        if r < 1.4:
            return 0.9
        if r < 2.0:
            return 1.0 + (r - 1.4) / 0.6 * 0.2
        return 1.3

    # ETH: 0.7 / 0.85 / 1.0 / 1.2~1.4 / 1.5
    if r < 0.7:
        return 0.7
    if r < 1.0:
        return 0.85
    if r < 1.4:
        return 1.0
    if r < 2.0:
        return 1.2 + (r - 1.4) / 0.6 * 0.2
    return 1.5


def resolve_coef(coef: float | None, profile: BreathingProfile | None = None) -> float:
    p = profile or ETH_PROFILE
    try:
        c = float(coef if coef is not None else 1.0)
    except (TypeError, ValueError):
        c = 1.0
    if c <= 0:
        c = 1.0
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
        "trail_tighten": profile.trail_tighten,
        "coef_min": profile.coef_min,
        "coef_max": profile.coef_max,
    }
