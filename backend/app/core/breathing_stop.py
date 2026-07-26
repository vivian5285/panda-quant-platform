"""Breathing stop — shared engine; ETH/XAU differ only via breathing_profile.

Phase 1: early BE + ATR step ladder × locked initial_atr (no breath coef)
Phase 2: trail = initial_atr × trailDistanceMultiplier(smoothedRatio)
initial_atr = VPS native 1h ATR when available, else TV atr (scenario 2);
coef from continuous interpolation of atr_1h / initial_atr.
"""

from __future__ import annotations

import math
from typing import Any

from app.core.breathing_profile import (
    ETH_PROFILE,
    cold_start_multiplier,
    effective_radar_arm_distance,
    get_breathing_coefficient_for_profile,
    profile_for_symbol,
    radar_arm_distance,
    radar_start_ratio,
    resolve_coef,
    COLD_START_RATIO,
)
from app.core.symbol_registry import symbol_meta

# Module-level defaults = ETH (back-compat for imports/tests)
INITIAL_SL_ATR = ETH_PROFILE.initial_sl_atr
STEP_TRIGGER_ATR = ETH_PROFILE.step_trigger_atr  # legacy alias — live path unused
STEP_ADVANCE_ATR = ETH_PROFILE.step_advance_atr
BREAKEVEN_TRIGGER_ATR = ETH_PROFILE.phase2_trigger_atr
TP1_ATR = ETH_PROFILE.tp1_atr
TP1_FLOOR_ATR = ETH_PROFILE.tp1_floor_atr
TP2_ATR = ETH_PROFILE.tp2_atr
TP2_FLOOR_ATR = ETH_PROFILE.tp2_floor_atr
TP3_ATR = ETH_PROFILE.tp3_atr
DEFAULT_ATR = 30.0
DEFAULT_BREATHING_COEF = cold_start_multiplier(ETH_PROFILE)
STOP_ORDER_BUFFER_USDT = ETH_PROFILE.stop_order_buffer

ADX_WEAK_BOUND = 15.0
ADX_STRONG_BOUND = 35.0
TRAIL_DIST_WEAK_ATR = ETH_PROFILE.coef_min
TRAIL_DIST_STRONG_ATR = ETH_PROFILE.coef_max
DEFAULT_ADX = 25.0


def get_breathing_coefficient(smooth_ratio: float, symbol: str | None = None) -> float:
    return get_breathing_coefficient_for_profile(
        smooth_ratio, profile_for_symbol(symbol),
    )


def resolve_breathing_coef(coef: float | None, symbol: str | None = None) -> float:
    return resolve_coef(coef, profile_for_symbol(symbol))


def default_breathing_coef(symbol: str | None = None) -> float:
    """Idle / missing-seed default = continuous cold-start (not literal 1.0)."""
    return cold_start_multiplier(profile_for_symbol(symbol))


def load_breathing_coef(raw: Any, symbol: str | None = None) -> float:
    """State load: missing/non-positive → cold-start; else keep value (tick clamps)."""
    if raw is None:
        return default_breathing_coef(symbol)
    try:
        c = float(raw)
    except (TypeError, ValueError):
        return default_breathing_coef(symbol)
    if c != c or c <= 0:  # NaN or non-positive
        return default_breathing_coef(symbol)
    return c


def trail_distance_by_adx(adx_val: float) -> float:
    """Legacy ADX trail helper — maps to ETH continuous ends (kept for imports)."""
    adx = float(adx_val if adx_val is not None else DEFAULT_ADX)
    if adx <= ADX_WEAK_BOUND:
        return TRAIL_DIST_WEAK_ATR
    if adx >= ADX_STRONG_BOUND:
        return TRAIL_DIST_STRONG_ATR
    ratio = (adx - ADX_WEAK_BOUND) / (ADX_STRONG_BOUND - ADX_WEAK_BOUND)
    return TRAIL_DIST_WEAK_ATR + ratio * (TRAIL_DIST_STRONG_ATR - TRAIL_DIST_WEAK_ATR)


def resolve_atr(atr: float | None) -> float:
    a = float(atr or 0)
    return a if a > 0 else DEFAULT_ATR


def resolve_adx(adx: float | None) -> float:
    try:
        a = float(adx if adx is not None else DEFAULT_ADX)
    except (TypeError, ValueError):
        return DEFAULT_ADX
    return a if a > 0 else DEFAULT_ADX


def _price_tick(symbol: str | None) -> float:
    try:
        meta = symbol_meta(symbol) if symbol else {}
        tick = float(meta.get("price_tick") or 0.01)
        return tick if tick > 0 else 0.01
    except Exception:
        return 0.01


TEMP_TV_STOP_BUFFER = 1.15  # whitepaper v3 fixed breathing pad (not tiered)
# Deprecated — radar floor / slip no longer widen hard stop (2026-07-25 TV sync).
HARD_VS_RADAR_FLOOR = 1.05  # retained for tests/compat imports only
HARD_SLIP_MULT = 0.0  # slip pad removed; hard = |TV.e−SL| × buffer from fill
HARD_STOP_MIN_TICKS = 5  # reject open if tv_stop_distance < N ticks


def compute_initial_stop(
    entry: float,
    side: str,
    atr: float,
    symbol: str | None = None,
) -> float:
    """Logical radar initial stop (no exchange buffer). Unrelated to hard stop."""
    p = profile_for_symbol(symbol)
    entry = float(entry or 0)
    atr = resolve_atr(atr)
    if entry <= 0:
        return 0.0
    if side == "LONG":
        return entry - p.initial_sl_atr * atr
    if side == "SHORT":
        return entry + p.initial_sl_atr * atr
    return 0.0


def hard_stop_buffer_mult(
    symbol: str | None = None,
    *,
    trend_tier: int | None = None,
) -> float:
    """Whitepaper v3: fixed 1.15 for ETH/XAU all tiers."""
    _ = (symbol, trend_tier)
    try:
        from app.core.trend_tier_params import HARD_STOP_BUFFER_FIXED
        from app.config import get_settings

        s = get_settings()
        return float(
            getattr(s, "HARD_STOP_BUFFER_MULT", None)
            or HARD_STOP_BUFFER_FIXED
            or TEMP_TV_STOP_BUFFER
        )
    except Exception:
        return float(TEMP_TV_STOP_BUFFER)


def hard_stop_min_ticks(symbol: str | None = None) -> int:
    try:
        from app.config import get_settings

        return int(getattr(get_settings(), "HARD_STOP_MIN_TICKS", HARD_STOP_MIN_TICKS) or HARD_STOP_MIN_TICKS)
    except Exception:
        return int(HARD_STOP_MIN_TICKS)


def compute_hard_stop_distance(
    *,
    fill_entry: float,
    tv_stop_loss: float,
    tv_entry: float | None = None,
    initial_atr: float | None = None,
    symbol: str | None = None,
    slip_mult: float | None = None,
    buffer_mult: float | None = None,
    trend_tier: int | None = None,
) -> dict[str, float]:
    """Hard-stop distance from TV (whitepaper v3).

    tv_stop_distance = |TV.price − TV.stop_loss|
    actual = tv_stop_distance × 1.15  (fixed; not ADX-tiered)
    Hang = fill ± actual  (no ATR floor, no fill-slip pad).

    ``initial_atr`` / ``slip_mult`` kept for call-site compat; ignored.
    """
    fill = float(fill_entry or 0)
    tv_sl = float(tv_stop_loss or 0)
    tv_e = float(tv_entry or 0) or fill
    buf = float(
        buffer_mult
        if buffer_mult is not None
        else hard_stop_buffer_mult(symbol, trend_tier=trend_tier)
    )
    if buf <= 0:
        buf = float(TEMP_TV_STOP_BUFFER)
    out = {
        "tv_stop_distance": 0.0,
        "tv_implied_dist": 0.0,  # alias = actual after buffer (compat)
        "radar_floor_dist": 0.0,  # always 0 — floor removed
        "base_dist": 0.0,
        "slip_dist": 0.0,
        "final_dist": 0.0,
        "fill_entry": fill,
        "tv_entry": tv_e,
        "buffer_mult": buf,
        "min_ticks": float(hard_stop_min_ticks(symbol)),
        "tick": float(_price_tick(symbol)),
        "reject_reason": "",
    }
    if fill <= 0 or tv_sl <= 0 or tv_e <= 0:
        out["reject_reason"] = "missing_tv_stop_or_entry"
        return out
    raw = abs(tv_e - tv_sl)
    out["tv_stop_distance"] = raw
    tick = float(out["tick"] or 0.01)
    min_ticks = int(out["min_ticks"] or HARD_STOP_MIN_TICKS)
    if raw + 1e-12 < tick * max(1, min_ticks):
        out["reject_reason"] = "tv_stop_distance_too_small"
        return out
    actual = raw * buf
    out["tv_implied_dist"] = actual
    out["base_dist"] = actual
    out["final_dist"] = actual
    return out


def compute_temp_tv_stop(
    entry: float,
    side: str,
    tv_stop_loss: float,
    *,
    tv_entry: float | None = None,
    initial_atr: float | None = None,
    symbol: str | None = None,
    slip_mult: float | None = None,
    buffer_mult: float | None = None,
    trend_tier: int | None = None,
) -> float:
    """Permanent hard stop from fill: fill ± (|TV.e−SL| × buffer).

    Missing / tiny TV stop_loss → 0 (caller fail-closes). ATR ignored.
    """
    fill = float(entry or 0)
    side_u = str(side or "").upper()
    if fill <= 0 or side_u not in ("LONG", "SHORT"):
        return 0.0
    meta = compute_hard_stop_distance(
        fill_entry=fill,
        tv_stop_loss=tv_stop_loss,
        tv_entry=tv_entry,
        initial_atr=initial_atr,
        symbol=symbol,
        slip_mult=slip_mult,
        buffer_mult=buffer_mult,
        trend_tier=trend_tier,
    )
    dist = float(meta.get("final_dist") or 0)
    if dist <= 0:
        return 0.0
    if side_u == "LONG":
        return fill - dist
    return fill + dist


def hard_stop_meta_for_logs(
    *,
    fill_entry: float,
    tv_stop_loss: float,
    tv_entry: float | None = None,
    symbol: str | None = None,
) -> dict[str, float | str]:
    """Fields required by deploy spec §6 for open logs."""
    meta = compute_hard_stop_distance(
        fill_entry=fill_entry,
        tv_stop_loss=tv_stop_loss,
        tv_entry=tv_entry,
        symbol=symbol,
    )
    return {
        "tv_stop_loss": float(tv_stop_loss or 0),
        "tv_stop_distance": float(meta.get("tv_stop_distance") or 0),
        "actual_stop_distance": float(meta.get("final_dist") or 0),
        "buffer_mult": float(meta.get("buffer_mult") or TEMP_TV_STOP_BUFFER),
        "reject_reason": str(meta.get("reject_reason") or ""),
    }


def tv_raw_stop_distance(
    *,
    tv_stop_loss: float,
    tv_entry: float | None = None,
    fill_entry: float | None = None,
    initial_atr: float | None = None,
) -> float:
    """TV original stop distance (no 1.2 buffer). Fallback ≈1×ATR."""
    tv_sl = float(tv_stop_loss or 0)
    tv_e = float(tv_entry or 0) or float(fill_entry or 0)
    if tv_sl > 0 and tv_e > 0:
        return abs(tv_e - tv_sl)
    atr = float(initial_atr or 0)
    return atr if atr > 0 else 0.0


def compute_radar_stagnant_tighten_stop(
    fill_entry: float,
    side: str,
    tv_stop_loss: float,
    *,
    tv_entry: float | None = None,
    initial_atr: float | None = None,
) -> float:
    """One-shot stagnant tighten target: fill ± TV raw distance (Option A).

    Does **not** touch hard stop. Used when chart-window expires without
    reaching the dynamic radar arm threshold.
    """
    fill = float(fill_entry or 0)
    side_u = str(side or "").upper()
    if fill <= 0 or side_u not in ("LONG", "SHORT"):
        return 0.0
    dist = tv_raw_stop_distance(
        tv_stop_loss=tv_stop_loss,
        tv_entry=tv_entry,
        fill_entry=fill,
        initial_atr=initial_atr,
    )
    if dist <= 0:
        return 0.0
    if side_u == "LONG":
        return fill - dist
    return fill + dist


def favorable_move(side: str | None, entry: float, price: float) -> float:
    side_u = str(side or "").upper()
    e = float(entry or 0)
    px = float(price or 0)
    if e <= 0 or px <= 0:
        return 0.0
    if side_u == "LONG":
        return max(0.0, px - e)
    if side_u == "SHORT":
        return max(0.0, e - px)
    return 0.0


def radar_arm_reached(
    side: str | None,
    entry: float,
    price: float,
    initial_atr: float,
    smooth_ratio: float | None = None,
    symbol: str | None = None,
    *,
    arm_tp1_pct: float | None = None,
    tp1_dist: float | None = None,
    tv_entry: float | None = None,
    tp1: float | None = None,
    tp2: float | None = None,
    is_reentry: bool | None = None,
) -> bool:
    """True when price hits §6.1 arm: first=(TP1+TP2)/2, reentry=TP2."""
    from app.core.trend_tier_params import RADAR_ARM_TP1_PCT, radar_armed_by_price

    del smooth_ratio  # dynamic vol arm purged (§14)
    pct = float(arm_tp1_pct if arm_tp1_pct is not None else RADAR_ARM_TP1_PCT)
    return bool(
        radar_armed_by_price(
            side=str(side or ""),
            price=float(price or 0),
            fill_entry=float(entry or 0),
            tp1=float(tp1 or 0),
            tp2=float(tp2 or 0),
            tv_entry=tv_entry,
            tp1_dist=tp1_dist,
            atr=float(initial_atr or 0),
            symbol=symbol,
            arm_pct=pct,
            is_reentry=is_reentry,
        )
    )


def apply_stop_order_buffer(
    side: str | None,
    stop: float,
    symbol: str | None = None,
) -> float:
    """Exchange hang price: LONG −buffer / SHORT +buffer (ETH 0.3 / XAU 0.5)."""
    sl = float(stop or 0)
    if sl <= 0:
        return 0.0
    buf = float(profile_for_symbol(symbol).stop_order_buffer)
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return sl - buf
    if side_u == "SHORT":
        return sl + buf
    return sl


def compute_tp_ladder_from_atr(
    entry: float,
    side: str,
    atr: float | None = None,
    symbol: str | None = None,
) -> list[float]:
    p = profile_for_symbol(symbol)
    entry_v = float(entry or 0)
    atr_v = resolve_atr(atr)
    side_u = str(side or "").upper()
    if entry_v <= 0 or side_u not in ("LONG", "SHORT"):
        return [0.0, 0.0, 0.0]
    sign = 1.0 if side_u == "LONG" else -1.0
    return [
        entry_v + sign * p.tp1_atr * atr_v,
        entry_v + sign * p.tp2_atr * atr_v,
        entry_v + sign * p.tp3_atr * atr_v,
    ]


def init_breathing_state(
    entry: float,
    side: str,
    atr: float | None = None,
    breathing_coefficient: float | None = None,
    symbol: str | None = None,
    **_legacy: Any,
) -> dict[str, Any]:
    p = profile_for_symbol(symbol)
    atr_v = resolve_atr(atr)
    coef = resolve_coef(breathing_coefficient, p) if breathing_coefficient is not None else cold_start_multiplier(p)
    entry_v = float(entry or 0)
    stop = compute_initial_stop(entry_v, side, atr_v, symbol=symbol)
    return {
        "entry_price": entry_v,
        "initial_atr": atr_v,
        "initial_stop": stop,
        "current_sl": stop,
        "best_price": entry_v,
        "breakeven_phase": False,
        "breathing_coefficient": coef,
        "step_count": 0,
        "remaining_qty_pct": 1.0,
        "side": side,
        "symbol_tag": p.symbol_tag,
        "current_adx": float(_legacy.get("adx") or DEFAULT_ADX) if _legacy.get("adx") else DEFAULT_ADX,
    }


def _tier_overrides(legacy: dict[str, Any], profile) -> dict[str, float | None]:
    """Pull ADX-tier / reentry overrides from kwargs (None = use profile)."""
    _ = profile

    def _f(key: str) -> float | None:
        if key not in legacy or legacy.get(key) is None:
            return None
        try:
            v = float(legacy[key])
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None

    # Prefer explicit tp1_dist; accept radar_tp1_distance alias from persisted state
    tp1_d = _f("tp1_dist")
    if tp1_d is None:
        tp1_d = _f("radar_tp1_distance")

    return {
        "arm_tp1_pct": _f("arm_tp1_pct"),
        "step_trigger_atr": _f("step_trigger_atr"),
        "early_breakeven_atr": _f("early_breakeven_atr"),
        "step_advance_atr": _f("step_advance_atr"),
        "coef_min": _f("coef_min"),
        "coef_max": _f("coef_max"),
        "breath_tp1_tp2_atr": _f("breath_tp1_tp2_atr"),
        "breath_tp2_tp3_atr": _f("breath_tp2_tp3_atr"),
        "tp1_price": _f("tp1_price"),
        "tp2_price": _f("tp2_price"),
        "tp3_price": _f("tp3_price"),
        "tv_entry": _f("tv_entry"),
        "tp1_dist": tp1_d,
        "radar_activated": legacy.get("radar_activated"),
        "is_reentry": legacy.get("is_reentry"),
        "reentry_attempt": legacy.get("reentry_attempt"),
    }


def _resolve_tp_prices(
    entry: float,
    atr: float,
    side: str,
    symbol: str | None,
    ov: dict[str, float | None],
) -> tuple[float, float, float]:
    p = profile_for_symbol(symbol)
    sign = 1.0 if str(side).upper() == "LONG" else -1.0
    t1 = float(ov.get("tp1_price") or 0) or (entry + sign * p.tp1_atr * atr)
    t2 = float(ov.get("tp2_price") or 0) or (entry + sign * p.tp2_atr * atr)
    t3 = float(ov.get("tp3_price") or 0) or (entry + sign * p.tp3_atr * atr)
    return t1, t2, t3


def calculate_stop_long(
    price: float,
    entry_price: float,
    initial_atr: float,
    initial_stop: float,
    current_stop: float,
    highest_price: float,
    breakeven_phase: bool,
    breathing_coefficient: float = DEFAULT_BREATHING_COEF,
    symbol: str | None = None,
    smooth_ratio: float | None = None,
    **_legacy: Any,
) -> tuple[float, float, bool, dict[str, Any]]:
    """§6.1: arm at (TP1+TP2)/2 first / TP2 reentry; activate entry+0.5ATR; trail."""
    from app.core.trend_tier_params import (
        RADAR_ACTIVATE_BE_ATR,
        RADAR_ARM_TP1_PCT,
        is_reentry_attempt,
        radar_arm_trigger_price,
        radar_armed_by_price,
    )

    p = profile_for_symbol(symbol)
    ov = _tier_overrides(_legacy, p)
    step_adv_atr = float(ov["step_advance_atr"] if ov["step_advance_atr"] is not None else p.step_advance_atr)
    step_trig = float(ov["step_trigger_atr"] if ov["step_trigger_atr"] is not None else p.step_trigger_atr)
    arm_pct = float(ov["arm_tp1_pct"] if ov["arm_tp1_pct"] is not None else RADAR_ARM_TP1_PCT)
    activate_be = float(ov["early_breakeven_atr"] if ov["early_breakeven_atr"] is not None else RADAR_ACTIVATE_BE_ATR)
    cmin = ov["coef_min"]
    cmax = ov["coef_max"]
    breath12 = float(ov["breath_tp1_tp2_atr"] or 1.2)
    breath23 = float(ov["breath_tp2_tp3_atr"] or 1.6)
    tv_e = float(ov["tv_entry"] or 0)
    tp1_d = float(ov["tp1_dist"] or 0)
    try:
        re_att = int(ov.get("reentry_attempt") or 0)
    except (TypeError, ValueError):
        re_att = 0
    reentry = is_reentry_attempt(re_att, is_reentry=ov.get("is_reentry"))

    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = resolve_atr(initial_atr)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    highest_price = float(highest_price or entry_price or 0)
    coef = resolve_coef(
        breathing_coefficient, p,
        coef_min=cmin, coef_max=cmax,
    )
    sr = float(smooth_ratio if smooth_ratio is not None else COLD_START_RATIO)
    tp1, tp2, tp3 = _resolve_tp_prices(entry_price, initial_atr, "LONG", symbol, ov)

    new_highest = max(highest_price, price) if price > 0 else highest_price
    new_stop = current_stop if current_stop > 0 else initial_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {
        "mode": "phase2" if new_phase else "phase1",
        "breathing_coefficient": coef,
        "symbol_tag": p.symbol_tag,
        "arm_tp1_pct": arm_pct,
        "step_trigger_atr": step_trig,
        "step_advance_atr": step_adv_atr,
        "early_breakeven_atr": activate_be,
        "coef_min": float(cmin if cmin is not None else p.coef_min),
        "coef_max": float(cmax if cmax is not None else p.coef_max),
        "breath_tp1_tp2_atr": breath12,
        "breath_tp2_tp3_atr": breath23,
        "tv_entry": tv_e,
        "tp1_dist": tp1_d,
        "is_reentry": reentry,
        "tp1": tp1,
        "tp2": tp2,
    }

    arm_kw = dict(
        side="LONG",
        fill_entry=entry_price,
        tp1=tp1,
        tp2=tp2,
        tv_entry=tv_e if tv_e > 0 else None,
        tp1_dist=tp1_d if tp1_d > 0 else None,
        atr=initial_atr,
        symbol=symbol,
        arm_pct=arm_pct,
        is_reentry=reentry,
    )
    arm_trig = radar_arm_trigger_price(**arm_kw)
    arm_dist = abs(arm_trig - entry_price) if arm_trig > 0 else 0.0
    meta["radar_arm_dist"] = arm_dist
    meta["radar_arm_trigger"] = arm_trig
    meta["radar_arm_ratio"] = arm_pct
    meta["radar_arm_mode"] = "tp2" if reentry else "tp1_tp2_mid"
    already = bool(ov.get("radar_activated"))
    armed = already or radar_armed_by_price(price=price, **arm_kw)
    meta["radar_armed"] = armed

    if not armed:
        meta["event"] = "waiting_arm"
        meta["step_count"] = 0
        return new_stop, new_highest, new_phase, meta

    activate_stop = entry_price + activate_be * initial_atr
    trail_dist = initial_atr * coef
    step_advance = step_adv_atr * initial_atr
    step_size = step_trig * initial_atr if step_trig > 0 else 0.0

    if not already:
        # First activation: lift stop to entry+0.5ATR
        candidate = max(new_stop, activate_stop) if new_stop > 0 else activate_stop
        if candidate > current_stop + 1e-12 or current_stop <= 0:
            event = "radar_activate"
        new_stop = candidate
        meta["event"] = event
        meta["step_count"] = 0
        meta["just_activated"] = True
        # May continue into same-tick trail if already deep in profit
        already = True

    move = max(0.0, price - entry_price) if price > 0 else 0.0
    extra = max(0.0, move - arm_dist)
    steps_after = max(0, int(math.floor(extra / step_size))) if step_size > 0 else 0
    step_count = steps_after
    step_stop = activate_stop + step_count * step_advance

    # Breath zone by TP path
    if price + 1e-12 >= tp3:
        breath = coef  # phase2 uses continuous coef band
        new_phase = True
        zone = "tp3_trail"
    elif price + 1e-12 >= tp2:
        breath = breath23
        zone = "tp2_tp3"
    else:
        breath = breath12
        zone = "tp1_tp2"
    meta["breath_zone"] = zone
    meta["breath_atr"] = breath
    trail_stop = new_highest - breath * initial_atr
    candidate = max(new_stop, step_stop, trail_stop, activate_stop)
    if new_phase:
        trailed = new_highest - trail_dist
        candidate = max(candidate, trailed)
        if event == "none":
            event = "phase2_enter" if not breakeven_phase else "trail"
        meta["mode"] = "phase2"
        meta["trail_dist_atr"] = coef
        meta["trail_distance"] = trail_dist
    elif candidate > new_stop + 1e-12 and event == "none":
        event = "step" if step_count > 0 else "trail"

    new_stop = candidate
    meta["event"] = event
    meta["step_count"] = step_count
    return new_stop, new_highest, new_phase, meta


def calculate_stop_short(
    price: float,
    entry_price: float,
    initial_atr: float,
    initial_stop: float,
    current_stop: float,
    lowest_price: float,
    breakeven_phase: bool,
    breathing_coefficient: float = DEFAULT_BREATHING_COEF,
    symbol: str | None = None,
    smooth_ratio: float | None = None,
    **_legacy: Any,
) -> tuple[float, float, bool, dict[str, Any]]:
    """§6.1 short: arm at (TP1+TP2)/2 first / TP2 reentry; activate entry−0.5ATR."""
    from app.core.trend_tier_params import (
        RADAR_ACTIVATE_BE_ATR,
        RADAR_ARM_TP1_PCT,
        is_reentry_attempt,
        radar_arm_trigger_price,
        radar_armed_by_price,
    )

    p = profile_for_symbol(symbol)
    ov = _tier_overrides(_legacy, p)
    step_adv_atr = float(ov["step_advance_atr"] if ov["step_advance_atr"] is not None else p.step_advance_atr)
    step_trig = float(ov["step_trigger_atr"] if ov["step_trigger_atr"] is not None else p.step_trigger_atr)
    arm_pct = float(ov["arm_tp1_pct"] if ov["arm_tp1_pct"] is not None else RADAR_ARM_TP1_PCT)
    activate_be = float(ov["early_breakeven_atr"] if ov["early_breakeven_atr"] is not None else RADAR_ACTIVATE_BE_ATR)
    cmin = ov["coef_min"]
    cmax = ov["coef_max"]
    breath12 = float(ov["breath_tp1_tp2_atr"] or 1.0)
    breath23 = float(ov["breath_tp2_tp3_atr"] or 1.4)
    tv_e = float(ov["tv_entry"] or 0)
    tp1_d = float(ov["tp1_dist"] or 0)
    try:
        re_att = int(ov.get("reentry_attempt") or 0)
    except (TypeError, ValueError):
        re_att = 0
    reentry = is_reentry_attempt(re_att, is_reentry=ov.get("is_reentry"))

    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = resolve_atr(initial_atr)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    lowest_price = float(lowest_price or entry_price or 0)
    coef = resolve_coef(
        breathing_coefficient, p,
        coef_min=cmin, coef_max=cmax,
    )
    sr = float(smooth_ratio if smooth_ratio is not None else COLD_START_RATIO)
    _ = sr
    tp1, tp2, tp3 = _resolve_tp_prices(entry_price, initial_atr, "SHORT", symbol, ov)

    new_lowest = min(lowest_price, price) if price > 0 else lowest_price
    if lowest_price <= 0 and price > 0:
        new_lowest = price
    new_stop = current_stop if current_stop > 0 else initial_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {
        "mode": "phase2" if new_phase else "phase1",
        "breathing_coefficient": coef,
        "symbol_tag": p.symbol_tag,
        "arm_tp1_pct": arm_pct,
        "step_trigger_atr": step_trig,
        "step_advance_atr": step_adv_atr,
        "early_breakeven_atr": activate_be,
        "coef_min": float(cmin if cmin is not None else p.coef_min),
        "coef_max": float(cmax if cmax is not None else p.coef_max),
        "breath_tp1_tp2_atr": breath12,
        "breath_tp2_tp3_atr": breath23,
        "tv_entry": tv_e,
        "tp1_dist": tp1_d,
        "is_reentry": reentry,
        "tp1": tp1,
        "tp2": tp2,
    }

    arm_kw = dict(
        side="SHORT",
        fill_entry=entry_price,
        tp1=tp1,
        tp2=tp2,
        tv_entry=tv_e if tv_e > 0 else None,
        tp1_dist=tp1_d if tp1_d > 0 else None,
        atr=initial_atr,
        symbol=symbol,
        arm_pct=arm_pct,
        is_reentry=reentry,
    )
    arm_trig = radar_arm_trigger_price(**arm_kw)
    arm_dist = abs(entry_price - arm_trig) if arm_trig > 0 else 0.0
    meta["radar_arm_dist"] = arm_dist
    meta["radar_arm_trigger"] = arm_trig
    meta["radar_arm_ratio"] = arm_pct
    meta["radar_arm_mode"] = "tp2" if reentry else "tp1_tp2_mid"
    already = bool(ov.get("radar_activated"))
    armed = already or radar_armed_by_price(price=price, **arm_kw)
    meta["radar_armed"] = armed

    if not armed:
        meta["event"] = "waiting_arm"
        meta["step_count"] = 0
        return new_stop, new_lowest, new_phase, meta

    activate_stop = entry_price - activate_be * initial_atr
    trail_dist = initial_atr * coef
    step_advance = step_adv_atr * initial_atr
    step_size = step_trig * initial_atr if step_trig > 0 else 0.0

    if not already:
        if current_stop <= 0:
            candidate = activate_stop
        else:
            candidate = min(current_stop, activate_stop)
        if current_stop <= 0 or candidate < current_stop - 1e-12:
            event = "radar_activate"
        new_stop = candidate
        meta["event"] = event
        meta["step_count"] = 0
        meta["just_activated"] = True
        already = True

    move = max(0.0, entry_price - price) if price > 0 else 0.0
    extra = max(0.0, move - arm_dist)
    steps_after = max(0, int(math.floor(extra / step_size))) if step_size > 0 else 0
    step_count = steps_after
    step_stop = activate_stop - step_count * step_advance

    if price - 1e-12 <= tp3:
        breath = coef
        new_phase = True
        zone = "tp3_trail"
    elif price - 1e-12 <= tp2:
        breath = breath23
        zone = "tp2_tp3"
    else:
        breath = breath12
        zone = "tp1_tp2"
    meta["breath_zone"] = zone
    meta["breath_atr"] = breath
    trail_stop = new_lowest + breath * initial_atr
    if new_stop <= 0:
        candidate = min(step_stop, trail_stop, activate_stop)
    else:
        candidate = min(new_stop, step_stop, trail_stop, activate_stop)
    if new_phase:
        trailed = new_lowest + trail_dist
        candidate = min(candidate, trailed) if candidate > 0 else trailed
        if event == "none":
            event = "phase2_enter" if not breakeven_phase else "trail"
        meta["mode"] = "phase2"
        meta["trail_dist_atr"] = coef
        meta["trail_distance"] = trail_dist
    elif (new_stop <= 0 or candidate < new_stop - 1e-12) and event == "none":
        event = "step" if step_count > 0 else "trail"

    new_stop = candidate
    meta["event"] = event
    meta["step_count"] = step_count
    return new_stop, new_lowest, new_phase, meta


def apply_breathing_tick(
    *,
    side: str | None,
    price: float,
    entry_price: float,
    initial_atr: float,
    initial_stop: float,
    current_stop: float,
    best_price: float,
    breakeven_phase: bool,
    breathing_coefficient: float | None = None,
    adx_val: float | None = None,
    symbol: str | None = None,
    smooth_ratio: float | None = None,
    arm_tp1_pct: float | None = None,
    step_trigger_atr: float | None = None,
    early_breakeven_atr: float | None = None,
    step_advance_atr: float | None = None,
    coef_min: float | None = None,
    coef_max: float | None = None,
    breath_tp1_tp2_atr: float | None = None,
    breath_tp2_tp3_atr: float | None = None,
    tp1_price: float | None = None,
    tp2_price: float | None = None,
    tp3_price: float | None = None,
    radar_activated: bool | None = None,
    tv_entry: float | None = None,
    tp1_dist: float | None = None,
    radar_tp1_distance: float | None = None,
    is_reentry: bool | None = None,
    reentry_attempt: int | None = None,
) -> dict[str, Any]:
    from app.core.breathing_profile import trail_distance_multiplier

    p = profile_for_symbol(symbol)
    sr = float(smooth_ratio if smooth_ratio is not None else COLD_START_RATIO)
    if coef_min is not None or coef_max is not None:
        cmin = float(coef_min if coef_min is not None else p.coef_min)
        cmax = float(coef_max if coef_max is not None else p.coef_max)
        coef = trail_distance_multiplier(sr, p, coef_min=cmin, coef_max=cmax)
    else:
        coef = resolve_breathing_coef(breathing_coefficient, symbol)
    side_u = str(side or "").upper()
    dist = tp1_dist if tp1_dist is not None else radar_tp1_distance
    tier_kw = {
        "arm_tp1_pct": arm_tp1_pct,
        "step_trigger_atr": step_trigger_atr,
        "early_breakeven_atr": early_breakeven_atr,
        "step_advance_atr": step_advance_atr,
        "coef_min": coef_min,
        "coef_max": coef_max,
        "breath_tp1_tp2_atr": breath_tp1_tp2_atr,
        "breath_tp2_tp3_atr": breath_tp2_tp3_atr,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "tp3_price": tp3_price,
        "radar_activated": radar_activated,
        "tv_entry": tv_entry,
        "tp1_dist": dist,
        "is_reentry": is_reentry,
        "reentry_attempt": reentry_attempt,
    }
    if side_u == "LONG":
        new_stop, peak, phase, meta = calculate_stop_long(
            price, entry_price, initial_atr, initial_stop,
            current_stop, best_price, breakeven_phase, coef,
            symbol=symbol, smooth_ratio=sr, **tier_kw,
        )
    elif side_u == "SHORT":
        new_stop, peak, phase, meta = calculate_stop_short(
            price, entry_price, initial_atr, initial_stop,
            current_stop, best_price, breakeven_phase, coef,
            symbol=symbol, smooth_ratio=sr, **tier_kw,
        )
    else:
        return {
            "current_sl": float(current_stop or 0),
            "best_price": float(best_price or 0),
            "breakeven_phase": bool(breakeven_phase),
            "event": "none",
            "improved": False,
            "meta": {},
            "breathing_coefficient": coef,
        }

    old = float(current_stop or 0)
    improved = False
    if side_u == "LONG":
        improved = new_stop > old + 1e-12
    else:
        improved = (old <= 0 and new_stop > 0) or (old > 0 and new_stop < old - 1e-12)

    return {
        "current_sl": float(new_stop),
        "best_price": float(peak),
        "breakeven_phase": bool(phase),
        "event": meta.get("event") or "none",
        "improved": improved,
        "breathing_coefficient": coef,
        "step_count": int(meta.get("step_count") or 0),
        "adx": resolve_adx(adx_val),
        "meta": meta,
        "initial_atr": resolve_atr(initial_atr),
        "initial_stop": float(initial_stop or 0),
        "symbol_tag": meta.get("symbol_tag"),
        "radar_armed": bool(meta.get("radar_armed")),
    }


def stop_hit(side: str | None, price: float, current_stop: float) -> bool:
    px = float(price or 0)
    sl = float(current_stop or 0)
    if px <= 0 or sl <= 0:
        return False
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return px <= sl
    if side_u == "SHORT":
        return px >= sl
    return False


def format_breathing_legend(symbol: str | None = None) -> str:
    from app.core.trend_tier_params import params_for_tier

    p = profile_for_symbol(symbol)
    mid = params_for_tier(1, symbol)
    return (
        f"[{p.symbol_tag}] 硬止损呼吸垫固定1.15"
        f" · 档位弱/中/强(ADX<20/20–30/>30)调雷达步长"
        f" · 雷达启动=(TP1+TP2)/2首次|TP2重入→entry±0.5ATR"
        f" · 步进{mid.step_trigger_atr}/{mid.step_advance_atr}×ATR(中档)"
        f" · 追踪{mid.trail_coef_min}~{mid.trail_coef_max}×ATR"
        f" · 重入仅强趋势·最多1次/{mid.reentry_bars}根K"
    )
