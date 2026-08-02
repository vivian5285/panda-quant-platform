"""Trend-tier parameters for radar trail / reentry — absolute price anchor only.

Hard-stop buffer: FIXED 1.15 (unified, not tiered).
Radar arm: Spec §6.1 — absolute price anchor only:
  First open: (TP1 + TP2) / 2
  Reentry: TP2
No ADX bands, no percentage-based arm distances.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.symbol_registry import CANONICAL_BNB, CANONICAL_ETH, CANONICAL_XAU, normalize_canonical_symbol

DEFAULT_TREND_TIER = 1  # mid when ADX missing
MAX_REENTRY = 1
HARD_STOP_BUFFER_FIXED = 1.15  # v3: unified, not tiered
RADAR_ARM_MODE_ABSOLUTE = "absolute_price_anchor"  # Spec §6.1
# Kept for compat imports only — arm uses absolute_price_anchor
RADAR_ARM_MODE_ADX = "adx_70_80_90"


@dataclass(frozen=True)
class TrendTierParams:
    """Per-symbol × tier radar trail / reentry knobs (hard buffer is global 1.15)."""

    tier: int
    hard_buffer: float  # always HARD_STOP_BUFFER_FIXED
    step_trigger_atr: float
    step_advance_atr: float
    early_breakeven_atr: float
    breath_tp1_tp2_atr: float
    breath_tp2_tp3_atr: float
    trail_coef_min: float
    trail_coef_max: float
    reentry_bars: int
    reentry_zone_atr: float
    chart_tf_min: float

    @property
    def tier_label(self) -> str:
        return {0: "弱趋势", 1: "中趋势", 2: "强趋势"}.get(int(self.tier), f"t{self.tier}")

    @property
    def reentry_window_sec(self) -> float:
        return float(self.reentry_bars) * float(self.chart_tf_min) * 60.0

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tier_label"] = self.tier_label
        d["reentry_window_sec"] = self.reentry_window_sec
        return d


def _tier_row(
    *,
    tier: int,
    step_trigger_atr: float,
    step_advance_atr: float,
    early_breakeven_atr: float,
    breath_tp1_tp2_atr: float,
    breath_tp2_tp3_atr: float,
    trail_coef_min: float,
    trail_coef_max: float,
    reentry_bars: int,
    reentry_zone_atr: float,
    chart_tf_min: float,
) -> TrendTierParams:
    return TrendTierParams(
        tier=tier,
        hard_buffer=HARD_STOP_BUFFER_FIXED,
        step_trigger_atr=step_trigger_atr,
        step_advance_atr=step_advance_atr,
        early_breakeven_atr=early_breakeven_atr,
        breath_tp1_tp2_atr=breath_tp1_tp2_atr,
        breath_tp2_tp3_atr=breath_tp2_tp3_atr,
        trail_coef_min=trail_coef_min,
        trail_coef_max=trail_coef_max,
        reentry_bars=reentry_bars,
        reentry_zone_atr=reentry_zone_atr,
        chart_tf_min=chart_tf_min,
    )


# ETHUSDT.P — whitepaper trail table (hard buffer is global 1.15)
_ETH: tuple[TrendTierParams, ...] = (
    _tier_row(
        tier=0, step_trigger_atr=0.40, step_advance_atr=0.25,
        early_breakeven_atr=0.0,
        breath_tp1_tp2_atr=0.80, breath_tp2_tp3_atr=1.00,
        trail_coef_min=1.2, trail_coef_max=1.5,
        reentry_bars=2, reentry_zone_atr=0.5, chart_tf_min=90.0,
    ),
    _tier_row(
        tier=1, step_trigger_atr=0.50, step_advance_atr=0.35,
        early_breakeven_atr=0.5,
        breath_tp1_tp2_atr=1.20, breath_tp2_tp3_atr=1.60,
        trail_coef_min=2.0, trail_coef_max=2.5,
        reentry_bars=2, reentry_zone_atr=0.5, chart_tf_min=90.0,
    ),
    _tier_row(
        tier=2, step_trigger_atr=0.60, step_advance_atr=0.40,
        early_breakeven_atr=0.5,
        breath_tp1_tp2_atr=1.50, breath_tp2_tp3_atr=2.00,
        trail_coef_min=2.5, trail_coef_max=3.5,
        reentry_bars=2, reentry_zone_atr=0.5, chart_tf_min=90.0,
    ),
)

# XAUUSDT.P — trail table
_XAU: tuple[TrendTierParams, ...] = (
    _tier_row(
        tier=0, step_trigger_atr=0.35, step_advance_atr=0.20,
        early_breakeven_atr=0.0,
        breath_tp1_tp2_atr=0.70, breath_tp2_tp3_atr=0.90,
        trail_coef_min=1.0, trail_coef_max=1.3,
        reentry_bars=3, reentry_zone_atr=0.3, chart_tf_min=45.0,
    ),
    _tier_row(
        tier=1, step_trigger_atr=0.40, step_advance_atr=0.30,
        early_breakeven_atr=0.5,
        breath_tp1_tp2_atr=1.00, breath_tp2_tp3_atr=1.40,
        trail_coef_min=1.5, trail_coef_max=2.0,
        reentry_bars=3, reentry_zone_atr=0.3, chart_tf_min=45.0,
    ),
    _tier_row(
        tier=2, step_trigger_atr=0.50, step_advance_atr=0.35,
        early_breakeven_atr=0.5,
        breath_tp1_tp2_atr=1.30, breath_tp2_tp3_atr=1.80,
        trail_coef_min=2.0, trail_coef_max=2.8,
        reentry_bars=3, reentry_zone_atr=0.3, chart_tf_min=45.0,
    ),
)

# BNBUSDT — between ETH and XAU volatility
_BNB: tuple[TrendTierParams, ...] = (
    _tier_row(
        tier=0, step_trigger_atr=0.38, step_advance_atr=0.22,
        early_breakeven_atr=0.0,
        breath_tp1_tp2_atr=0.75, breath_tp2_tp3_atr=0.95,
        trail_coef_min=1.1, trail_coef_max=1.5,
        reentry_bars=2, reentry_zone_atr=0.4, chart_tf_min=60.0,
    ),
    _tier_row(
        tier=1, step_trigger_atr=0.45, step_advance_atr=0.32,
        early_breakeven_atr=0.5,
        breath_tp1_tp2_atr=1.10, breath_tp2_tp3_atr=1.50,
        trail_coef_min=1.8, trail_coef_max=2.3,
        reentry_bars=2, reentry_zone_atr=0.4, chart_tf_min=60.0,
    ),
    _tier_row(
        tier=2, step_trigger_atr=0.55, step_advance_atr=0.38,
        early_breakeven_atr=0.5,
        breath_tp1_tp2_atr=1.40, breath_tp2_tp3_atr=1.90,
        trail_coef_min=2.3, trail_coef_max=3.2,
        reentry_bars=2, reentry_zone_atr=0.4, chart_tf_min=60.0,
    ),
)


def _canon(symbol: str | None) -> str:
    return normalize_canonical_symbol(symbol) or CANONICAL_ETH


def adx_to_tier(adx: float | None) -> int:
    """ADX < 20 → 0; 20–30 → 1; > 30 → 2. Missing → mid (1)."""
    try:
        a = float(adx) if adx is not None else float("nan")
    except (TypeError, ValueError):
        return DEFAULT_TREND_TIER
    if a != a or a <= 0:
        return DEFAULT_TREND_TIER
    if a < 20.0:
        return 0
    if a <= 30.0:
        return 1
    return 2


def clamp_tier(tier: int | None) -> int:
    try:
        t = int(tier) if tier is not None else DEFAULT_TREND_TIER
    except (TypeError, ValueError):
        return DEFAULT_TREND_TIER
    return max(0, min(2, t))


def resolve_tier_from_payload(
    payload: dict[str, Any] | None = None,
    *,
    adx: float | None = None,
    tv_stop_distance: float | None = None,
    atr: float | None = None,
) -> int:
    """Prefer webhook ``tier`` (0/1/2); else ADX; else tv_stop_distance/atr heuristic."""
    if payload:
        raw = payload.get("tier", payload.get("trend_tier"))
        if raw is not None and str(raw).strip() != "":
            try:
                return clamp_tier(int(raw))
            except (TypeError, ValueError):
                pass
        if adx is None:
            try:
                adx = float(payload.get("adx") or 0) or None
            except (TypeError, ValueError):
                adx = None
    if adx is not None:
        return adx_to_tier(adx)
    try:
        dist = float(tv_stop_distance or 0)
        a = float(atr or 0)
    except (TypeError, ValueError):
        return DEFAULT_TREND_TIER
    if dist > 0 and a > 0:
        ratio = dist / a
        if ratio < 1.2:
            return 0
        if ratio > 1.8:
            return 2
        return 1
    return DEFAULT_TREND_TIER


def effective_radar_tier(adx_tier: int, boost: int = 0) -> int:
    """Reentry loosens trail params by +1 tier (cap 2); TP prices unchanged."""
    return clamp_tier(clamp_tier(adx_tier) + max(0, int(boost or 0)))


def params_for_tier(tier: int, symbol: str | None = None) -> TrendTierParams:
    can = _canon(symbol)
    if can == CANONICAL_XAU:
        table = _XAU
    elif can == CANONICAL_BNB:
        table = _BNB
    else:
        table = _ETH
    return table[clamp_tier(tier)]


def params_for_adx(adx: float | None, symbol: str | None = None, *, boost: int = 0) -> TrendTierParams:
    return params_for_tier(effective_radar_tier(adx_to_tier(adx), boost), symbol)


def hard_buffer_for_tier(_tier: int | None = None, symbol: str | None = None) -> float:
    """v3: always 1.15 — tier/symbol ignored (compat signature retained)."""
    _ = (_tier, symbol)
    return float(HARD_STOP_BUFFER_FIXED)


# Spec §6.0: early breakeven checkpoint parameters
EARLY_BREAKEVEN_TP1_RATIO = 0.5  # TP1 distance 50% → breakeven move


def early_breakeven_trigger_price(
    entry: float,
    tp1: float,
    side: str,
) -> float:
    """Spec §6.0: trigger price for early breakeven checkpoint.

    tp1_distance = |tp1 - entry|
    Long: entry + tp1_distance × 0.5
    Short: entry - tp1_distance × 0.5
    """
    e = float(entry or 0)
    t1 = float(tp1 or 0)
    side_u = str(side or "").upper()
    if e <= 0 or t1 <= 0 or side_u not in ("LONG", "SHORT"):
        return 0.0
    tp1_dist = abs(t1 - e)
    if side_u == "LONG":
        return e + tp1_dist * EARLY_BREAKEVEN_TP1_RATIO
    else:
        return e - tp1_dist * EARLY_BREAKEVEN_TP1_RATIO


def early_breakeven_reached(
    curr_px: float,
    entry: float,
    tp1: float,
    side: str,
) -> bool:
    """Check if early breakeven checkpoint is reached."""
    trig = early_breakeven_trigger_price(entry, tp1, side)
    if trig <= 0:
        return False
    px = float(curr_px or 0)
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return px >= trig
    else:
        return px <= trig


# Spec §6.1: absolute price anchor radar arm
def radar_arm_absolute_trigger(tp1: float, tp2: float, *, is_reentry: bool) -> float:
    """Spec §6.1: radar arm trigger — absolute price anchor.

    First open: (TP1 + TP2) / 2
    Reentry: TP2
    """
    t1 = float(tp1 or 0)
    t2 = float(tp2 or 0)
    if t1 <= 0 or t2 <= 0:
        return 0.0
    if is_reentry:
        return t2
    else:
        return (t1 + t2) / 2.0


def radar_armed_by_absolute_price(
    *,
    side: str,
    price: float,
    tp1: float,
    tp2: float,
    is_reentry: bool = False,
) -> bool:
    """Spec §6.1: check if price has reached absolute price anchor arm point."""
    trig = radar_arm_absolute_trigger(tp1, tp2, is_reentry=is_reentry)
    if trig <= 0:
        return False
    px = float(price or 0)
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return px + 1e-12 >= trig
    else:
        return px - 1e-12 <= trig


def reentry_zone_atr(symbol: str | None = None) -> float:
    return float(params_for_tier(1, symbol).reentry_zone_atr)


def reentry_window_sec(symbol: str | None = None, tier: int | None = None) -> float:
    return float(params_for_tier(clamp_tier(tier if tier is not None else 1), symbol).reentry_window_sec)


def tp1_distance(tv_entry: float, tp1: float) -> float:
    """|webhook.tp1 − webhook.price| — absolute distance."""
    e = float(tv_entry or 0)
    t1 = float(tp1 or 0)
    if e <= 0 or t1 <= 0:
        return 0.0
    return abs(t1 - e)


def is_reentry_attempt(attempt: int = 0, *, is_reentry: bool | None = None) -> bool:
    if is_reentry is not None:
        return bool(is_reentry)
    return int(attempt or 0) >= 1


def radar_arm_trigger_price(
    *,
    side: str,
    entry: float | None = None,
    fill_entry: float | None = None,
    tp1: float = 0.0,
    tp2: float = 0.0,
    tv_entry: float | None = None,
    tp1_dist: float | None = None,
    atr: float = 0.0,
    symbol: str | None = None,
    arm_pct: float | None = None,
    adx: float | None = None,
    is_reentry: bool | None = None,
    attempt: int | None = None,
) -> float:
    """Spec §6.1: arm trigger price — absolute anchor when TP1/TP2 available.

    Falls back to no-arm (return 0) if TP1/TP2 unavailable.
    """
    t1 = float(tp1 or 0)
    t2 = float(tp2 or 0)
    if t1 > 0 and t2 > 0:
        reentry = bool(is_reentry) or (int(attempt or 0) >= 1)
        return radar_arm_absolute_trigger(t1, t2, is_reentry=reentry)
    # No TP1/TP2 available → no arm
    return 0.0


def radar_armed_by_price(
    *,
    side: str,
    price: float,
    entry: float | None = None,
    fill_entry: float | None = None,
    tp1: float = 0.0,
    tp2: float = 0.0,
    tv_entry: float | None = None,
    tp1_dist: float | None = None,
    atr: float = 0.0,
    symbol: str | None = None,
    arm_pct: float | None = None,
    adx: float | None = None,
    is_reentry: bool | None = None,
    attempt: int | None = None,
) -> bool:
    px = float(price or 0)
    trig = radar_arm_trigger_price(
        side=side,
        entry=entry,
        fill_entry=fill_entry,
        tp1=tp1,
        tp2=tp2,
        tv_entry=tv_entry,
        tp1_dist=tp1_dist,
        atr=atr,
        symbol=symbol,
        arm_pct=arm_pct,
        adx=adx,
        is_reentry=is_reentry,
        attempt=attempt,
    )
    if px <= 0 or trig <= 0:
        return False
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return px + 1e-12 >= trig
    if side_u == "SHORT":
        return px - 1e-12 <= trig
    return False
