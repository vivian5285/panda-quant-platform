"""ADX trend-tier + radar-arm parameters — Marathon radar (fix版 2026-07-28).

Trail tiers (separate from arm):
  Tier 0 weak (ADX < 20), tier 1 mid (20–30), tier 2 strong (ADX > 30).

Radar arm — Layer 1 (ADX discrete start ratio × TP1 distance):
  ADX < 20 → 70% (早激活·保护微利); ADX 20–30 → 80%; ADX > 30 → 90% (晚激活·留呼吸).
  弱早强晚：弱趋势毛刺少但回撤也小，早点保本；强趋势回踩深，晚点介入。
  Arm distance = (1.35 × initial_atr) × start_ratio; trigger = fill ± distance.
  Independent of TP1 fill. Activate lift = fee+tick BE (not entry±0.5ATR).

Hard-stop buffer FIXED 1.15; reentry still loosens trail params +1 ADX tier.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.symbol_registry import CANONICAL_ETH, CANONICAL_XAU, normalize_canonical_symbol

ADX_WEAK = 20.0
ADX_STRONG = 30.0
DEFAULT_TREND_TIER = 1  # mid when ADX missing

# Layer-1 radar arm — marathon discrete bands (弱早强晚; aligned ADX_WEAK/STRONG).
# Ranges in doc: weak 65–70% → 70%; mid 75–80% → 80%; strong 85–90% → 90%.
RADAR_ARM_ADX_WEAK = ADX_WEAK  # <20 → weak ratio
RADAR_ARM_ADX_STRONG = ADX_STRONG  # >30 → strong ratio
RADAR_ARM_RATIO_WEAK = 0.70  # early arm — protect micro-profit
RADAR_ARM_RATIO_MID = 0.80
RADAR_ARM_RATIO_STRONG = 0.90  # late arm — room for deep pullbacks
RADAR_ARM_TP1_ATR = 1.35  # TP1 distance = 1.35 × initial_atr
DEFAULT_ARM_ADX = 25.0  # mid band → 80%

# Compat aliases — LIVE mid default
RADAR_ARM_TP1_PCT = RADAR_ARM_RATIO_MID
RADAR_ARM_TP1_PCT_REENTRY = RADAR_ARM_RATIO_MID  # LIVE ignores attempt; same ADX formula
# LEGACY: activate used entry±0.5ATR — marathon uses fee+tick BE (see fee_cover_breakeven_stop).
RADAR_ACTIVATE_BE_ATR = 0.0
MAX_REENTRY = 1
HARD_STOP_BUFFER_FIXED = 1.15  # v3: unified, not tiered
RADAR_ARM_MODE_ADX = "adx_70_80_90"
RADAR_ARM_MODE_ABSOLUTE = "absolute_price_anchor"  # Spec §6.1
# Deprecated mode tags kept for log parsers / old tests imports
RADAR_ARM_MODE_FIRST = RADAR_ARM_MODE_ADX
RADAR_ARM_MODE_REENTRY = RADAR_ARM_MODE_ADX


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

# XAUUSDT.P — marathon 修复版跟踪表（步长/跟进/TP3后追踪距离）
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
        trail_coef_min=1.5, trail_coef_max=2.0,
        reentry_bars=3, reentry_zone_atr=0.3, chart_tf_min=45.0,
    ),
    _tier_row(
        tier=2, step_trigger_atr=0.50, step_advance_atr=0.35,
        breath_tp1_tp2_atr=1.30, breath_tp2_tp3_atr=1.80,
        trail_coef_min=2.0, trail_coef_max=2.8,
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
    """Deprecated attempt-based hint — LIVE arm uses ``radar_arm_ratio_by_adx``."""
    _ = attempt
    return float(RADAR_ARM_TP1_PCT)


def radar_arm_ratio_by_adx(adx: float | None) -> float:
    """Layer-1 start ratio: ADX<20→70%, 20–30→80%, >30→90% (弱早强晚)."""
    try:
        a = float(adx) if adx is not None else float(DEFAULT_ARM_ADX)
    except (TypeError, ValueError):
        a = float(DEFAULT_ARM_ADX)
    if a != a:  # NaN
        a = float(DEFAULT_ARM_ADX)
    if a < float(RADAR_ARM_ADX_WEAK):
        return float(RADAR_ARM_RATIO_WEAK)
    if a > float(RADAR_ARM_ADX_STRONG):
        return float(RADAR_ARM_RATIO_STRONG)
    return float(RADAR_ARM_RATIO_MID)


def tp1_atr_distance(initial_atr: float, symbol: str | None = None) -> float:
    """TP1 distance = 1.35 × initial_atr (profile.tp1_atr when available)."""
    a = float(initial_atr or 0)
    if a <= 0:
        return 0.0
    try:
        from app.core.breathing_profile import profile_for_symbol

        mult = float(profile_for_symbol(symbol).tp1_atr or RADAR_ARM_TP1_ATR)
    except Exception:
        mult = float(RADAR_ARM_TP1_ATR)
    if mult <= 0:
        mult = float(RADAR_ARM_TP1_ATR)
    return mult * a


def is_reentry_attempt(attempt: int = 0, *, is_reentry: bool | None = None) -> bool:
    if is_reentry is not None:
        return bool(is_reentry)
    return int(attempt or 0) >= 1


def radar_arm_absolute_trigger(tp1: float, tp2: float, *, is_reentry: bool) -> float:
    """Spec §6.1 绝对价格锚定雷达激活价格.

    首次开仓: (TP1 + TP2) / 2 (所有用户共用同一份TV信号)
    重入开仓: TP2 (必须价格真正到达TP2)

    Args:
        tp1: TV信号的TP1绝对价格
        tp2: TV信号的TP2绝对价格
        is_reentry: True表示重入开仓

    Returns:
        雷达激活触发价格（绝对价格）
    """
    t1 = float(tp1 or 0)
    t2 = float(tp2 or 0)
    if t1 <= 0 or t2 <= 0:
        return 0.0
    if is_reentry:
        # 重入：必须等价格真正到达TP2
        return t2
    else:
        # 首次开仓：TP1-TP2区间中点
        return (t1 + t2) / 2.0


# Spec §6.0 提前保本检查点参数
EARLY_BREAKEVEN_TP1_RATIO = 0.5  # TP1距离的50%处触发保本移动


def early_breakeven_trigger_price(
    entry: float,
    tp1: float,
    side: str,
) -> float:
    """Spec §6.0 提前保本检查点触发价格.

    计算公式：
      tp1_distance = |tp1 - entry|
      多单：保本检查点 = entry + tp1_distance × 0.5
      空单：保本检查点 = entry - tp1_distance × 0.5

    触发后只移动止损到保本位，不启动雷达跟踪状态。

    Args:
        entry: 用户实际成交价
        tp1: TV信号的TP1绝对价格
        side: LONG 或 SHORT

    Returns:
        提前保本检查点触发价格
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
    """检查是否达到提前保本检查点.

    Args:
        curr_px: 当前价格
        entry: 用户实际成交价
        tp1: TV信号的TP1绝对价格
        side: LONG 或 SHORT

    Returns:
        True表示已达到提前保本检查点
    """
    trig = early_breakeven_trigger_price(entry, tp1, side)
    if trig <= 0:
        return False
    px = float(curr_px or 0)
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return px >= trig
    else:
        return px <= trig


def radar_armed_by_absolute_price(
    *,
    side: str,
    price: float,
    tp1: float,
    tp2: float,
    is_reentry: bool = False,
) -> bool:
    """Spec §6.1 检查价格是否达到绝对价格锚定的雷达激活点.

    首次开仓: 价格 >= (TP1 + TP2) / 2 (多单) 或 <= (多单)
    重入开仓: 价格 >= TP2 (多单) 或 <= (空单)

    Args:
        side: LONG 或 SHORT
        price: 当前价格
        tp1: TV信号的TP1绝对价格
        tp2: TV信号的TP2绝对价格
        is_reentry: True表示重入开仓

    Returns:
        True表示已达到雷达激活价格
    """
    trig = radar_arm_absolute_trigger(tp1, tp2, is_reentry=is_reentry)
    if trig <= 0:
        return False
    px = float(price or 0)
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return px >= trig
    else:
        return px <= trig


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
    """LIVE arm: fill ± (1.35×ATR × ADX_ratio 70/80/90). Independent of TP1 fill.

    ``arm_pct`` optional test override; otherwise ADX drives the ratio.
    ``tp1``/``tp2``/``is_reentry`` retained for call-site compat (ignored for trigger).
    """
    _ = (tp1, tp2, tv_entry, is_reentry, attempt)
    side_u = str(side or "").upper()
    fill = float(fill_entry if fill_entry is not None else (entry or 0))
    if fill <= 0 or side_u not in ("LONG", "SHORT"):
        return 0.0

    if arm_pct is not None:
        try:
            pct = float(arm_pct)
        except (TypeError, ValueError):
            pct = 0.0
        if pct <= 0:
            pct = radar_arm_ratio_by_adx(adx)
    else:
        pct = radar_arm_ratio_by_adx(adx)

    # Prefer ATR×1.35 (final spec). Optional explicit tp1_dist only if ATR missing.
    dist = tp1_atr_distance(atr, symbol)
    if dist <= 0:
        dist = float(tp1_dist or 0)
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
