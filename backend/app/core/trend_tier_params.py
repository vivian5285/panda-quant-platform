"""ADX trend-tier parameters — whitepaper v3.0 (2026-07-25).

Tier 0 weak (ADX < 20), tier 1 mid (20–30), tier 2 strong (ADX > 30).
ETH 90m / XAU 45m.

v3 corrections vs v2:
  - hard-stop buffer FIXED 1.15 (no ADX tier split)
  - radar arm = fill ± tp1_distance × ratio (first 0.85 / reentry 1.00)
  - reentry still loosens trail params +1 ADX tier
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.symbol_registry import CANONICAL_ETH, CANONICAL_XAU, normalize_canonical_symbol

ADX_WEAK = 20.0
ADX_STRONG = 30.0
DEFAULT_TREND_TIER = 1  # mid when ADX missing
RADAR_ARM_TP1_PCT = 0.85  # first open
RADAR_ARM_TP1_PCT_REENTRY = 1.00  # after reentry (v3)
RADAR_ACTIVATE_BE_ATR = 0.5  # on arm: stop → entry ± 0.5×ATR
MAX_REENTRY = 1
HARD_STOP_BUFFER_FIXED = 1.15  # v3: unified, not tiered


@dataclass(frozen=True)
class TrendTierParams:
    """Per-symbol × ADX-tier radar trail / reentry knobs (hard buffer is global)."""

    tier: int
    hard_buffer: float  # always HARD_STOP_BUFFER_FIXED (kept for compat dumps)
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


def _tier_row(
    *,
    tier: int,
    step_trigger_atr: float,
    step_advance_atr: float,
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
        breath_tp1_tp2_atr=breath_tp1_tp2_atr,
        breath_tp2_tp3_atr=breath_tp2_tp3_atr,
        trail_coef_min=trail_coef_min,
        trail_coef_max=trail_coef_max,
        reentry_bars=reentry_bars,
        reentry_zone_atr=reentry_zone_atr,
        chart_tf_min=chart_tf_min,
    )


# ETHUSDT.P — whitepaper §2.2 (trail knobs only; hard buffer unified)
_ETH: tuple[TrendTierParams, ...] = (
    _tier_row(
        tier=0, step_trigger_atr=0.40, step_advance_atr=0.25,
        breath_tp1_tp2_atr=0.80, breath_tp2_tp3_atr=1.00,
        trail_coef_min=1.2, trail_coef_max=1.5,
        reentry_bars=2, reentry_zone_atr=0.5, chart_tf_min=90.0,
    ),
    _tier_row(
        tier=1, step_trigger_atr=0.50, step_advance_atr=0.35,
        breath_tp1_tp2_atr=1.20, breath_tp2_tp3_atr=1.60,
        trail_coef_min=2.0, trail_coef_max=2.5,
        reentry_bars=2, reentry_zone_atr=0.5, chart_tf_min=90.0,
    ),
    _tier_row(
        tier=2, step_trigger_atr=0.60, step_advance_atr=0.40,
        breath_tp1_tp2_atr=1.50, breath_tp2_tp3_atr=2.00,
        trail_coef_min=2.5, trail_coef_max=3.5,
        reentry_bars=2, reentry_zone_atr=0.5, chart_tf_min=90.0,
    ),
)

# XAUUSDT.P — whitepaper §2.3
_XAU: tuple[TrendTierParams, ...] = (
    _tier_row(
        tier=0, step_trigger_atr=0.35, step_advance_atr=0.20,
        breath_tp1_tp2_atr=0.70, breath_tp2_tp3_atr=0.90,
        trail_coef_min=1.0, trail_coef_max=1.3,
        reentry_bars=3, reentry_zone_atr=0.3, chart_tf_min=45.0,
    ),
    _tier_row(
        tier=1, step_trigger_atr=0.40, step_advance_atr=0.30,
        breath_tp1_tp2_atr=1.00, breath_tp2_tp3_atr=1.40,
        trail_coef_min=1.8, trail_coef_max=2.2,
        reentry_bars=3, reentry_zone_atr=0.3, chart_tf_min=45.0,
    ),
    _tier_row(
        tier=2, step_trigger_atr=0.50, step_advance_atr=0.35,
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
    # Transition heuristic (§3.5): distance / ATR
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
    """Reentry success loosens trail params by +1 tier (cap 2); TP prices unchanged."""
    return clamp_tier(clamp_tier(adx_tier) + max(0, int(boost or 0)))


def params_for_tier(tier: int, symbol: str | None = None) -> TrendTierParams:
    can = _canon(symbol)
    table = _XAU if can == CANONICAL_XAU else _ETH
    return table[clamp_tier(tier)]


def params_for_adx(adx: float | None, symbol: str | None = None, *, boost: int = 0) -> TrendTierParams:
    return params_for_tier(effective_radar_tier(adx_to_tier(adx), boost), symbol)


def hard_buffer_for_tier(_tier: int | None = None, symbol: str | None = None) -> float:
    """v3: always 1.15 — tier/symbol ignored (compat signature retained)."""
    _ = (_tier, symbol)
    return float(HARD_STOP_BUFFER_FIXED)


def arm_ratio_for_attempt(attempt: int = 0) -> float:
    """First open 0.85; after reentry 1.00 (whitepaper v3 §4.1 / §5.4)."""
    return float(RADAR_ARM_TP1_PCT_REENTRY if int(attempt or 0) >= 1 else RADAR_ARM_TP1_PCT)


def reentry_zone_atr(symbol: str | None = None) -> float:
    return float(params_for_tier(1, symbol).reentry_zone_atr)


def reentry_window_sec(symbol: str | None = None, tier: int | None = None) -> float:
    return float(params_for_tier(clamp_tier(tier if tier is not None else 1), symbol).reentry_window_sec)


def tp1_distance(tv_entry: float, tp1: float) -> float:
    """|webhook.tp1 − webhook.price| — distance, never absolute TP1×ratio."""
    e = float(tv_entry or 0)
    t1 = float(tp1 or 0)
    if e <= 0 or t1 <= 0:
        return 0.0
    return abs(t1 - e)


def radar_arm_trigger_price(
    *,
    side: str,
    entry: float | None = None,
    fill_entry: float | None = None,
    tp1: float = 0.0,
    tv_entry: float | None = None,
    tp1_dist: float | None = None,
    atr: float = 0.0,
    symbol: str | None = None,
    arm_pct: float = RADAR_ARM_TP1_PCT,
) -> float:
    """v3: fill ± tp1_distance × activation_ratio.

    tp1_distance = |TV.tp1 − TV.price| (prefer explicit ``tp1_dist`` / ``tv_entry``).
    Never compute ``TP1_absolute × 0.85``.
    """
    from app.core.breathing_profile import profile_for_symbol

    side_u = str(side or "").upper()
    fill = float(fill_entry if fill_entry is not None else (entry or 0))
    pct = float(arm_pct) if arm_pct and arm_pct > 0 else RADAR_ARM_TP1_PCT
    if fill <= 0 or side_u not in ("LONG", "SHORT"):
        return 0.0

    dist = float(tp1_dist or 0)
    if dist <= 0:
        tv_e = float(tv_entry or 0)
        t1 = float(tp1 or 0)
        if tv_e > 0 and t1 > 0:
            dist = abs(t1 - tv_e)
        elif t1 > 0 and fill > 0:
            # Last resort: treat tp1 vs fill (less accurate if fill slipped)
            dist = abs(t1 - fill)
        else:
            p = profile_for_symbol(symbol)
            a = float(atr or 0)
            if a <= 0:
                return 0.0
            dist = float(p.tp1_atr) * a

    if dist <= 0:
        return 0.0
    if side_u == "LONG":
        return fill + dist * pct
    return fill - dist * pct


def radar_armed_by_price(
    *,
    side: str,
    price: float,
    entry: float | None = None,
    fill_entry: float | None = None,
    tp1: float = 0.0,
    tv_entry: float | None = None,
    tp1_dist: float | None = None,
    atr: float = 0.0,
    symbol: str | None = None,
    arm_pct: float = RADAR_ARM_TP1_PCT,
) -> bool:
    px = float(price or 0)
    trig = radar_arm_trigger_price(
        side=side,
        entry=entry,
        fill_entry=fill_entry,
        tp1=tp1,
        tv_entry=tv_entry,
        tp1_dist=tp1_dist,
        atr=atr,
        symbol=symbol,
        arm_pct=arm_pct,
    )
    if px <= 0 or trig <= 0:
        return False
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return px + 1e-12 >= trig
    if side_u == "SHORT":
        return px - 1e-12 <= trig
    return False
