"""ADX trend-tier parameters — whitepaper v2.0 (2026-07-25).

Tier 0 weak (ADX < 20), tier 1 mid (20–30), tier 2 strong (ADX > 30).
ETH 90m / XAU 45m; radar arms at path 85% to TP1; reentry max once.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.symbol_registry import CANONICAL_ETH, CANONICAL_XAU, normalize_canonical_symbol

ADX_WEAK = 20.0
ADX_STRONG = 30.0
DEFAULT_TREND_TIER = 1  # mid when ADX missing
RADAR_ARM_TP1_PCT = 0.85
RADAR_ACTIVATE_BE_ATR = 0.5  # on arm: stop → entry ± 0.5×ATR
MAX_REENTRY = 1


@dataclass(frozen=True)
class TrendTierParams:
    """Per-symbol × ADX-tier radar / hard-stop / reentry knobs."""

    tier: int
    hard_buffer: float
    step_trigger_atr: float
    step_advance_atr: float
    breath_tp1_tp2_atr: float
    breath_tp2_tp3_atr: float
    trail_coef_min: float
    trail_coef_max: float
    reentry_bars: int
    reentry_zone_atr: float
    chart_tf_min: float
    radar_arm_tp1_pct: float = RADAR_ARM_TP1_PCT
    activate_be_atr: float = RADAR_ACTIVATE_BE_ATR

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


# ETHUSDT.P — whitepaper §2.2
_ETH: tuple[TrendTierParams, ...] = (
    TrendTierParams(
        tier=0, hard_buffer=1.1,
        step_trigger_atr=0.40, step_advance_atr=0.25,
        breath_tp1_tp2_atr=0.80, breath_tp2_tp3_atr=1.00,
        trail_coef_min=1.2, trail_coef_max=1.5,
        reentry_bars=2, reentry_zone_atr=0.5, chart_tf_min=90.0,
    ),
    TrendTierParams(
        tier=1, hard_buffer=1.2,
        step_trigger_atr=0.50, step_advance_atr=0.35,
        breath_tp1_tp2_atr=1.20, breath_tp2_tp3_atr=1.60,
        trail_coef_min=2.0, trail_coef_max=2.5,
        reentry_bars=2, reentry_zone_atr=0.5, chart_tf_min=90.0,
    ),
    TrendTierParams(
        tier=2, hard_buffer=1.3,
        step_trigger_atr=0.60, step_advance_atr=0.40,
        breath_tp1_tp2_atr=1.50, breath_tp2_tp3_atr=2.00,
        trail_coef_min=2.5, trail_coef_max=3.5,
        reentry_bars=2, reentry_zone_atr=0.5, chart_tf_min=90.0,
    ),
)

# XAUUSDT.P — whitepaper §2.3
_XAU: tuple[TrendTierParams, ...] = (
    TrendTierParams(
        tier=0, hard_buffer=1.1,
        step_trigger_atr=0.35, step_advance_atr=0.20,
        breath_tp1_tp2_atr=0.70, breath_tp2_tp3_atr=0.90,
        trail_coef_min=1.0, trail_coef_max=1.3,
        reentry_bars=3, reentry_zone_atr=0.3, chart_tf_min=45.0,
    ),
    TrendTierParams(
        tier=1, hard_buffer=1.2,
        step_trigger_atr=0.40, step_advance_atr=0.30,
        breath_tp1_tp2_atr=1.00, breath_tp2_tp3_atr=1.40,
        trail_coef_min=1.8, trail_coef_max=2.2,
        reentry_bars=3, reentry_zone_atr=0.3, chart_tf_min=45.0,
    ),
    TrendTierParams(
        tier=2, hard_buffer=1.3,
        step_trigger_atr=0.50, step_advance_atr=0.35,
        breath_tp1_tp2_atr=1.30, breath_tp2_tp3_atr=1.80,
        trail_coef_min=2.2, trail_coef_max=3.0,
        reentry_bars=3, reentry_zone_atr=0.3, chart_tf_min=45.0,
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
    if a != a or a <= 0:  # NaN / non-positive
        return DEFAULT_TREND_TIER
    if a < ADX_WEAK:
        return 0
    if a <= ADX_STRONG:
        return 1
    return 2


def clamp_tier(tier: int | None) -> int:
    try:
        t = int(tier) if tier is not None else DEFAULT_TREND_TIER
    except (TypeError, ValueError):
        return DEFAULT_TREND_TIER
    return max(0, min(2, t))


def effective_radar_tier(adx_tier: int, boost: int = 0) -> int:
    """Reentry success loosens radar by +1 tier (cap 2); TP prices unchanged."""
    return clamp_tier(clamp_tier(adx_tier) + max(0, int(boost or 0)))


def params_for_tier(tier: int, symbol: str | None = None) -> TrendTierParams:
    can = _canon(symbol)
    table = _XAU if can == CANONICAL_XAU else _ETH
    return table[clamp_tier(tier)]


def params_for_adx(adx: float | None, symbol: str | None = None, *, boost: int = 0) -> TrendTierParams:
    return params_for_tier(effective_radar_tier(adx_to_tier(adx), boost), symbol)


def hard_buffer_for_tier(tier: int, symbol: str | None = None) -> float:
    return float(params_for_tier(tier, symbol).hard_buffer)


def reentry_zone_atr(symbol: str | None = None) -> float:
    # Zone is symbol-constant across tiers in whitepaper
    return float(params_for_tier(1, symbol).reentry_zone_atr)


def reentry_window_sec(symbol: str | None = None, tier: int | None = None) -> float:
    return float(params_for_tier(clamp_tier(tier if tier is not None else 1), symbol).reentry_window_sec)


def radar_arm_trigger_price(
    *,
    side: str,
    entry: float,
    tp1: float,
    atr: float = 0.0,
    symbol: str | None = None,
    arm_pct: float = RADAR_ARM_TP1_PCT,
) -> float:
    """Path 85% to TP1 (whitepaper 「TP1×0.85」= near TP1, not literal price×0.85)."""
    from app.core.breathing_profile import profile_for_symbol

    side_u = str(side or "").upper()
    e = float(entry or 0)
    t1 = float(tp1 or 0)
    pct = float(arm_pct) if arm_pct and arm_pct > 0 else RADAR_ARM_TP1_PCT
    if e <= 0 or side_u not in ("LONG", "SHORT"):
        return 0.0
    if t1 <= 0:
        # Fallback: profile TP1 ATR distance
        p = profile_for_symbol(symbol)
        a = float(atr or 0)
        if a <= 0:
            return 0.0
        dist = float(p.tp1_atr) * a * pct
        return e + dist if side_u == "LONG" else e - dist
    if side_u == "LONG":
        return e + pct * (t1 - e)
    return e - pct * (e - t1)


def radar_armed_by_price(
    *,
    side: str,
    price: float,
    entry: float,
    tp1: float,
    atr: float = 0.0,
    symbol: str | None = None,
    arm_pct: float = RADAR_ARM_TP1_PCT,
) -> bool:
    px = float(price or 0)
    trig = radar_arm_trigger_price(
        side=side, entry=entry, tp1=tp1, atr=atr, symbol=symbol, arm_pct=arm_pct,
    )
    if px <= 0 or trig <= 0:
        return False
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return px + 1e-12 >= trig
    if side_u == "SHORT":
        return px - 1e-12 <= trig
    return False
