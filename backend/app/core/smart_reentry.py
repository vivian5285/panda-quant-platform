"""Dual-symbol smart re-entry — whitepaper v2.0 (2026-07-25).

Max 1 reentry after radar BE/micro-profit flat; ADX tier params;
dual-insurance limit price; hard-stop / loss closes never re-enter.
Radar arm fixed at TP1 path ×0.85; reentry success loosens radar +1 tier.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.symbol_registry import CANONICAL_ETH, CANONICAL_XAU, normalize_canonical_symbol
from app.core.trend_tier_params import (
    MAX_REENTRY,
    RADAR_ACTIVATE_BE_ATR,
    RADAR_ARM_TP1_PCT,
    TrendTierParams,
    adx_to_tier,
    clamp_tier,
    effective_radar_tier,
    params_for_tier,
    reentry_window_sec,
    reentry_zone_atr as _zone_atr,
)

# Re-export for callers / tests
ARM_TP1_PCTS: tuple[float, ...] = (RADAR_ARM_TP1_PCT,)
LIMIT_IMPROVE_PCT = 0.003
MAX_TIER_INDEX = 2  # ADX tiers 0..2
LIMIT_TTL_SEC = 300
MAX_UNFILLED_CYCLES = 5
MAX_DEV_FROM_TV_PCT = 0.01
REENTRY_ZONE_ATR = {
    CANONICAL_ETH: 0.5,
    CANONICAL_XAU: 0.3,
}


@dataclass(frozen=True)
class RadarTier:
    """Active radar coefficients for current ADX tier (+ optional reentry boost)."""

    attempt: int  # 0 = first open, 1 = after one reentry
    adx_tier: int
    radar_tier: int
    early_breakeven_atr: float  # activate BE = 0.5×ATR (whitepaper)
    step_trigger_atr: float
    step_advance_atr: float
    arm_tp1_pct: float
    coef_min: float
    coef_max: float
    breath_tp1_tp2_atr: float
    breath_tp2_tp3_atr: float
    hard_buffer: float
    tier_label: str
    reentry_bars: int
    chart_tf_min: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canon(symbol: str | None) -> str:
    return normalize_canonical_symbol(symbol) or CANONICAL_ETH


def smart_reentry_enabled_for(symbol: str | None) -> bool:
    try:
        from app.config import get_settings

        s = get_settings()
        can = _canon(symbol)
        if can == CANONICAL_XAU:
            return bool(getattr(s, "SMART_REENTRY_XAU_ENABLED", True))
        return bool(getattr(s, "SMART_REENTRY_ETH_ENABLED", True))
    except Exception:
        return True


def arm_tp1_pct_for_attempt(_attempt: int = 0) -> float:
    return float(RADAR_ARM_TP1_PCT)


def next_attempt_arm_pct(_prev_pct: float = 0.0) -> float:
    """Compat: arm is fixed 0.85 under whitepaper v2."""
    return float(RADAR_ARM_TP1_PCT)


def tier_for_attempt(
    attempt: int,
    symbol: str | None = None,
    *,
    adx_tier: int | None = None,
) -> RadarTier:
    """Map open/reentry attempt → radar params.

    attempt 0: radar_tier = adx_tier
    attempt ≥1: radar_tier = min(adx_tier+1, 2)  (one step looser)
    """
    base = clamp_tier(adx_tier if adx_tier is not None else 1)
    att = max(0, int(attempt))
    boost = 1 if att >= 1 else 0
    rt = effective_radar_tier(base, boost)
    p = params_for_tier(rt, symbol)
    return _params_to_radar_tier(p, attempt=min(att, MAX_REENTRY), adx_tier=base)


def tier_from_adx(
    adx: float | None,
    symbol: str | None = None,
    *,
    attempt: int = 0,
) -> RadarTier:
    return tier_for_attempt(attempt, symbol, adx_tier=adx_to_tier(adx))


def _params_to_radar_tier(p: TrendTierParams, *, attempt: int, adx_tier: int) -> RadarTier:
    return RadarTier(
        attempt=int(attempt),
        adx_tier=int(adx_tier),
        radar_tier=int(p.tier),
        early_breakeven_atr=float(RADAR_ACTIVATE_BE_ATR),
        step_trigger_atr=float(p.step_trigger_atr),
        step_advance_atr=float(p.step_advance_atr),
        arm_tp1_pct=float(RADAR_ARM_TP1_PCT),
        coef_min=float(p.trail_coef_min),
        coef_max=float(p.trail_coef_max),
        breath_tp1_tp2_atr=float(p.breath_tp1_tp2_atr),
        breath_tp2_tp3_atr=float(p.breath_tp2_tp3_atr),
        hard_buffer=float(p.hard_buffer),
        tier_label=p.tier_label,
        reentry_bars=int(p.reentry_bars),
        chart_tf_min=float(p.chart_tf_min),
    )


def reentry_zone_atr(symbol: str | None = None) -> float:
    can = _canon(symbol)
    return float(REENTRY_ZONE_ATR.get(can, _zone_atr(symbol)))


def arm_distance(
    atr: float,
    attempt: int = 0,
    symbol: str | None = None,
    *,
    arm_tp1_pct: float | None = None,
    step_trigger_atr: float | None = None,
    tp1: float | None = None,
    entry: float | None = None,
    adx_tier: int | None = None,
) -> float:
    """Favorable move to arm radar = path 85% to TP1 (or profile TP1×pct)."""
    from app.core.breathing_profile import profile_for_symbol
    from app.core.trend_tier_params import radar_arm_trigger_price

    a = float(atr or 0)
    e = float(entry or 0)
    t1 = float(tp1 or 0)
    pct = float(arm_tp1_pct if arm_tp1_pct is not None else RADAR_ARM_TP1_PCT)
    if e > 0 and t1 > 0:
        trig = radar_arm_trigger_price(
            side="LONG", entry=e, tp1=t1, atr=a, symbol=symbol, arm_pct=pct,
        )
        return abs(trig - e)
    p = profile_for_symbol(symbol)
    if a <= 0:
        return 0.0
    tier = tier_for_attempt(attempt, symbol, adx_tier=adx_tier)
    # Path distance ≈ TP1_atr × ATR × pct (no max with step_trigger — whitepaper is pure TP1×0.85)
    _ = step_trigger_atr  # unused; kept for call-site compat
    return float(p.tp1_atr) * a * float(tier.arm_tp1_pct if arm_tp1_pct is None else pct)


def limit_reentry_price(side: str, tv_px: float) -> float:
    px = float(tv_px or 0)
    if px <= 0:
        return 0.0
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return px * (1.0 - LIMIT_IMPROVE_PCT)
    if side_u == "SHORT":
        return px * (1.0 + LIMIT_IMPROVE_PCT)
    return 0.0


def _price_tick(symbol: str | None) -> float:
    try:
        from app.core.symbol_registry import symbol_meta

        meta = symbol_meta(symbol) or {}
        tick = float(meta.get("price_tick") or 0.01)
        return tick if tick > 0 else 0.01
    except Exception:
        return 0.01


def _kline_high_low(rows: list | None) -> tuple[float, float]:
    if not rows:
        return 0.0, 0.0
    row = rows[-1]
    try:
        hi = float(row[2])
        lo = float(row[3])
        if hi > 0 and lo > 0 and hi >= lo:
            return hi, lo
    except (TypeError, ValueError, IndexError):
        pass
    return 0.0, 0.0


def reentry_price_better_than_tv(side: str, limit_px: float, tv_px: float) -> bool:
    lim = float(limit_px or 0)
    tv = float(tv_px or 0)
    if lim <= 0 or tv <= 0:
        return False
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return lim < tv - 1e-12
    if side_u == "SHORT":
        return lim > tv + 1e-12
    return False


def reentry_price_better_than_entry(side: str, limit_px: float, entry: float) -> bool:
    """Whitepaper §5.3: reentry must beat last fill price."""
    lim = float(limit_px or 0)
    e = float(entry or 0)
    if lim <= 0 or e <= 0:
        return False
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return lim < e - 1e-12
    if side_u == "SHORT":
        return lim > e + 1e-12
    return False


def compute_optimal_reentry_price(
    *,
    side: str,
    tv_px: float,
    symbol: str | None = None,
    klines_5m: list | None = None,
    klines_3m: list | None = None,
    last_entry: float | None = None,
) -> tuple[float, dict[str, Any]]:
    """Dual-insurance + must beat TV; optionally must beat last entry."""
    side_u = str(side or "").upper()
    tv = float(tv_px or 0)
    tick = _price_tick(symbol)
    meta: dict[str, Any] = {"side": side_u, "tv_px": tv, "tick": tick}
    if side_u not in ("LONG", "SHORT") or tv <= 0:
        meta["reason"] = "bad_inputs"
        return 0.0, meta

    tv_cand = limit_reentry_price(side_u, tv)
    meta["tv_pct_candidate"] = tv_cand

    hi5, lo5 = _kline_high_low(klines_5m)
    hi3, lo3 = _kline_high_low(klines_3m)
    kline_cand = 0.0
    if hi5 > 0 and lo5 > 0:
        kline_cand = (lo5 + tick) if side_u == "LONG" else (hi5 - tick)
        meta["kline_source"] = "5m"
        meta["kline_high"] = hi5
        meta["kline_low"] = lo5
    elif hi3 > 0 and lo3 > 0:
        kline_cand = (lo3 + tick) if side_u == "LONG" else (hi3 - tick)
        meta["kline_source"] = "3m"
        meta["kline_high"] = hi3
        meta["kline_low"] = lo3
    else:
        meta["kline_source"] = None
    meta["kline_candidate"] = kline_cand

    if kline_cand > 0 and tv_cand > 0:
        if side_u == "LONG":
            candidate = min(kline_cand, tv_cand)
            meta["source"] = "dual_min"
        else:
            candidate = max(kline_cand, tv_cand)
            meta["source"] = "dual_max"
    elif kline_cand > 0:
        candidate = kline_cand
        meta["source"] = f"kline_{meta.get('kline_source')}"
    elif tv_cand > 0:
        candidate = tv_cand
        meta["source"] = "tv_pct_only"
    else:
        meta["reason"] = "no_candidate"
        return 0.0, meta

    if not reentry_price_better_than_tv(side_u, candidate, tv):
        meta["reason"] = "not_better_than_tv"
        meta["candidate"] = candidate
        return 0.0, meta

    entry = float(last_entry or 0)
    if entry > 0 and not reentry_price_better_than_entry(side_u, candidate, entry):
        meta["reason"] = "not_better_than_entry"
        meta["candidate"] = candidate
        meta["last_entry"] = entry
        return 0.0, meta

    meta["reason"] = "ok"
    meta["limit_px"] = float(candidate)
    return float(candidate), meta


def tv_deviation_ok(mark: float, tv_px: float, *, max_pct: float = MAX_DEV_FROM_TV_PCT) -> bool:
    m = float(mark or 0)
    t = float(tv_px or 0)
    if m <= 0 or t <= 0:
        return False
    return abs(m - t) / t <= float(max_pct)


def reentry_within_window(
    *,
    flat_ts: float,
    now_ts: float | None = None,
    symbol: str | None = None,
    adx_tier: int | None = None,
) -> tuple[bool, dict[str, Any]]:
    import time

    flat = float(flat_ts or 0)
    now = float(now_ts if now_ts is not None else time.time())
    win = reentry_window_sec(symbol, adx_tier)
    meta = {
        "flat_ts": flat,
        "now_ts": now,
        "window_sec": win,
        "elapsed_sec": max(0.0, now - flat) if flat > 0 else None,
    }
    if flat <= 0:
        meta["reason"] = "missing_flat_ts"
        return False, meta
    elapsed = now - flat
    if elapsed < 0:
        meta["reason"] = "clock_skew"
        return False, meta
    if elapsed > win + 1e-6:
        meta["reason"] = "window_expired"
        return False, meta
    meta["reason"] = "ok"
    meta["remaining_sec"] = max(0.0, win - elapsed)
    return True, meta


def close_allows_reentry(
    *,
    side: str,
    entry: float,
    close_px: float,
    atr: float,
    symbol: str | None,
    close_track: str,
    flat_ts: float | None = None,
    now_ts: float | None = None,
    adx_tier: int | None = None,
    reentry_attempt: int = 0,
) -> tuple[bool, dict[str, Any]]:
    meta: dict[str, Any] = {
        "side": str(side or "").upper(),
        "entry": float(entry or 0),
        "close_px": float(close_px or 0),
        "atr": float(atr or 0),
        "symbol": _canon(symbol),
        "close_track": str(close_track or "").lower(),
        "zone_atr": reentry_zone_atr(symbol),
        "reentry_attempt": int(reentry_attempt or 0),
    }
    if not smart_reentry_enabled_for(symbol):
        meta["reason"] = "disabled"
        return False, meta

    if int(reentry_attempt or 0) >= MAX_REENTRY:
        meta["reason"] = "max_reentry_once"
        return False, meta

    track = meta["close_track"]
    if track == "hard":
        meta["reason"] = "hard_stop_no_reentry"
        return False, meta
    if track not in ("radar",):
        meta["reason"] = "not_radar_close"
        return False, meta

    entry_px = float(entry or 0)
    exit_px = float(close_px or 0)
    atr_v = float(atr or 0)
    side_u = meta["side"]
    if entry_px <= 0 or exit_px <= 0 or atr_v <= 0 or side_u not in ("LONG", "SHORT"):
        meta["reason"] = "bad_inputs"
        return False, meta

    zone = reentry_zone_atr(symbol) * atr_v
    if side_u == "LONG" and exit_px < entry_px - 1e-12:
        meta["reason"] = "loss_no_reentry"
        return False, meta
    if side_u == "SHORT" and exit_px > entry_px + 1e-12:
        meta["reason"] = "loss_no_reentry"
        return False, meta

    if side_u == "LONG":
        lo, hi = entry_px, entry_px + zone
        in_zone = lo - 1e-9 <= exit_px <= hi + 1e-9
    else:
        lo, hi = entry_px - zone, entry_px
        in_zone = lo - 1e-9 <= exit_px <= hi + 1e-9
    meta["zone_lo"] = lo
    meta["zone_hi"] = hi
    if not in_zone:
        meta["reason"] = "outside_reentry_zone"
        return False, meta

    if flat_ts is not None:
        ok_w, wmeta = reentry_within_window(
            flat_ts=float(flat_ts), now_ts=now_ts, symbol=symbol, adx_tier=adx_tier,
        )
        meta["window"] = wmeta
        if not ok_w:
            meta["reason"] = wmeta.get("reason") or "window_expired"
            return False, meta

    meta["reason"] = "ok"
    return True, meta


def classify_stop_track(
    *,
    close_action: str | None = None,
    close_trigger: str | None = None,
    fill_px: float = 0.0,
    frozen_hard_px: float = 0.0,
    radar_sl_px: float = 0.0,
    side: str | None = None,
    near_pct: float = 0.0025,
) -> str:
    action = str(close_action or "").upper()
    trigger = str(close_trigger or "").lower()
    if "BREATH" in action or trigger in ("breathing_stop_hit", "radar_stop", "close_breath_stop"):
        return "radar"
    if "HARD" in action or trigger in ("hard_stop_hit", "adverse_hard"):
        return "hard"

    fill = float(fill_px or 0)
    hard = float(frozen_hard_px or 0)
    radar = float(radar_sl_px or 0)
    if fill <= 0:
        return "unknown"

    def _near(a: float, b: float) -> bool:
        if a <= 0 or b <= 0:
            return False
        return abs(a - b) / max(a, b) <= float(near_pct)

    near_hard = _near(fill, hard)
    near_radar = _near(fill, radar)
    if near_hard and not near_radar:
        return "hard"
    if near_radar and not near_hard:
        return "radar"
    if near_hard and near_radar:
        side_u = str(side or "").upper()
        if side_u == "LONG" and hard > 0 and radar > 0:
            return "hard" if fill <= hard + 1e-9 and hard <= radar else "radar"
        if side_u == "SHORT" and hard > 0 and radar > 0:
            return "hard" if fill >= hard - 1e-9 and hard >= radar else "radar"
        return "unknown"
    return "unknown"


def default_reentry_state() -> dict[str, Any]:
    t0 = tier_for_attempt(0, CANONICAL_ETH, adx_tier=1)
    return {
        "reentry_attempt": 0,
        "reentry_arm_tp1_pct": float(RADAR_ARM_TP1_PCT),
        "reentry_pending": False,
        "reentry_limit_oid": None,
        "reentry_limit_deadline": 0.0,
        "reentry_tv_side": None,
        "reentry_tv_px": 0.0,
        "last_close_track": None,
        "last_close_px": 0.0,
        "radar_flat_ts": 0.0,
        "trend_tier": 1,
        "radar_tier_boost": 0,
        "active_early_be_atr": float(t0.early_breakeven_atr),
        "active_step_trigger_atr": float(t0.step_trigger_atr),
        "active_step_advance_atr": float(t0.step_advance_atr),
        "active_coef_min": float(t0.coef_min),
        "active_coef_max": float(t0.coef_max),
        "active_breath_tp1_tp2_atr": float(t0.breath_tp1_tp2_atr),
        "active_breath_tp2_tp3_atr": float(t0.breath_tp2_tp3_atr),
        "active_hard_buffer": float(t0.hard_buffer),
        "reentry_tier_label": t0.tier_label,
        "reentry_abort_reason": None,
    }


def apply_tier_to_state(
    state: dict[str, Any],
    attempt: int,
    symbol: str | None,
    *,
    adx_tier: int | None = None,
) -> dict[str, Any]:
    base_tier = clamp_tier(
        adx_tier if adx_tier is not None else state.get("trend_tier", 1)
    )
    tier = tier_for_attempt(attempt, symbol, adx_tier=base_tier)
    out = dict(state or {})
    out["reentry_attempt"] = int(tier.attempt)
    out["reentry_arm_tp1_pct"] = float(tier.arm_tp1_pct)
    out["trend_tier"] = int(base_tier)
    out["radar_tier_boost"] = 1 if int(attempt) >= 1 else 0
    out["active_early_be_atr"] = float(tier.early_breakeven_atr)
    out["active_step_trigger_atr"] = float(tier.step_trigger_atr)
    out["active_step_advance_atr"] = float(tier.step_advance_atr)
    out["active_coef_min"] = float(tier.coef_min)
    out["active_coef_max"] = float(tier.coef_max)
    out["active_breath_tp1_tp2_atr"] = float(tier.breath_tp1_tp2_atr)
    out["active_breath_tp2_tp3_atr"] = float(tier.breath_tp2_tp3_atr)
    out["active_hard_buffer"] = float(tier.hard_buffer)
    out["reentry_tier_label"] = tier.tier_label
    return out


def reset_reentry_state(symbol: str | None = None, *, adx_tier: int | None = None) -> dict[str, Any]:
    base = default_reentry_state()
    return apply_tier_to_state(base, 0, symbol, adx_tier=adx_tier)
