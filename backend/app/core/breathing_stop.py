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


TEMP_TV_STOP_BUFFER = 1.2  # default buffer_multiplier (overridable via Settings)
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


def hard_stop_buffer_mult(symbol: str | None = None) -> float:
    """Configurable buffer_multiplier (ETH/XAU can diverge later)."""
    try:
        from app.config import get_settings
        from app.core.symbol_registry import CANONICAL_XAU, normalize_canonical_symbol

        s = get_settings()
        can = normalize_canonical_symbol(symbol) or ""
        if can == CANONICAL_XAU:
            return float(getattr(s, "HARD_STOP_BUFFER_MULT_XAU", None) or getattr(s, "HARD_STOP_BUFFER_MULT", TEMP_TV_STOP_BUFFER) or TEMP_TV_STOP_BUFFER)
        return float(getattr(s, "HARD_STOP_BUFFER_MULT_ETH", None) or getattr(s, "HARD_STOP_BUFFER_MULT", TEMP_TV_STOP_BUFFER) or TEMP_TV_STOP_BUFFER)
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
) -> dict[str, float]:
    """Hard-stop distance from TV (2026-07-25).

    tv_stop_distance = |TV.price − TV.stop_loss|
    actual = tv_stop_distance × buffer_multiplier
    Hang = fill ± actual  (no ATR floor, no fill-slip pad).

    ``initial_atr`` / ``slip_mult`` kept for call-site compat; ignored.
    """
    fill = float(fill_entry or 0)
    tv_sl = float(tv_stop_loss or 0)
    tv_e = float(tv_entry or 0) or fill
    buf = float(buffer_mult if buffer_mult is not None else hard_stop_buffer_mult(symbol))
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
) -> bool:
    """True when favorable move has reached dynamic first-move arm."""
    p = profile_for_symbol(symbol)
    atr = resolve_atr(initial_atr)
    sr = float(smooth_ratio if smooth_ratio is not None else COLD_START_RATIO)
    arm = radar_arm_distance(atr, sr, p)
    if arm <= 0:
        return False
    return favorable_move(side, entry, price) + 1e-12 >= arm


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
    """Pull smart-reentry tier overrides from kwargs (None = use profile)."""
    def _f(key: str) -> float | None:
        if key not in legacy or legacy.get(key) is None:
            return None
        try:
            v = float(legacy[key])
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None

    return {
        "arm_tp1_pct": _f("arm_tp1_pct"),
        "step_trigger_atr": _f("step_trigger_atr"),
        "early_breakeven_atr": _f("early_breakeven_atr"),
        "step_advance_atr": _f("step_advance_atr"),
        "coef_min": _f("coef_min"),
        "coef_max": _f("coef_max"),
    }


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
    p = profile_for_symbol(symbol)
    ov = _tier_overrides(_legacy, p)
    early_be = float(ov["early_breakeven_atr"] if ov["early_breakeven_atr"] is not None else p.early_breakeven_atr)
    step_adv_atr = float(ov["step_advance_atr"] if ov["step_advance_atr"] is not None else p.step_advance_atr)
    step_trig = float(ov["step_trigger_atr"] if ov["step_trigger_atr"] is not None else p.step_trigger_atr)
    arm_pct = ov["arm_tp1_pct"]
    cmin = ov["coef_min"]
    cmax = ov["coef_max"]

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
    tick = _price_tick(symbol)
    sr = float(smooth_ratio if smooth_ratio is not None else COLD_START_RATIO)

    new_highest = max(highest_price, price) if price > 0 else highest_price
    new_stop = current_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {
        "mode": "phase2" if new_phase else "phase1",
        "breathing_coefficient": coef,
        "symbol_tag": p.symbol_tag,
    }

    step_advance = step_adv_atr * initial_atr
    arm_dist = effective_radar_arm_distance(
        initial_atr, sr, p, arm_tp1_pct=arm_pct, step_trigger_atr=step_trig,
    )
    # Legacy dynamic ratio kept for logs only when no fixed pct
    arm_ratio = float(arm_pct) if arm_pct is not None else radar_start_ratio(sr, p)
    meta["radar_arm_ratio"] = arm_ratio
    meta["radar_arm_dist"] = arm_dist
    meta["arm_tp1_pct"] = arm_pct if arm_pct is not None else arm_ratio
    meta["step_trigger_atr"] = step_trig
    meta["early_breakeven_atr"] = early_be
    meta["step_advance_atr"] = step_adv_atr
    meta["coef_min"] = float(cmin if cmin is not None else p.coef_min)
    meta["coef_max"] = float(cmax if cmax is not None else p.coef_max)
    trail_dist = initial_atr * coef

    if not new_phase:
        move = max(0.0, price - entry_price) if price > 0 else 0.0
        if arm_dist <= 0 or move + 1e-12 < arm_dist:
            step_count = 0
            candidate = current_stop if current_stop > 0 else initial_stop
        else:
            extra = max(0.0, move - arm_dist)
            steps_after = (
                max(0, int(math.floor(extra / step_advance)))
                if step_advance > 0
                else 0
            )
            step_count = 1 + steps_after
            step_stop = initial_stop + step_count * step_advance
            candidate = max(current_stop, step_stop)
            if step_count > 0 and candidate > current_stop + 1e-12:
                event = "step"
        meta["step_count"] = step_count

        if early_be > 0 and price >= entry_price + early_be * initial_atr:
            be = entry_price + tick
            if be > candidate:
                candidate = be
                event = "early_breakeven"

        if price >= entry_price + p.tp1_atr * initial_atr:
            floor = entry_price + p.tp1_floor_atr * initial_atr
            if floor > candidate:
                candidate = floor
                event = "floor_tp1"
        if price >= entry_price + p.tp2_atr * initial_atr:
            floor = entry_price + p.tp2_floor_atr * initial_atr
            if floor > candidate:
                candidate = floor
                event = "floor_tp2"

        new_stop = candidate

        if price >= entry_price + p.phase2_trigger_atr * initial_atr:
            new_phase = True
            trailed = new_highest - trail_dist
            new_stop = max(new_stop, trailed)
            event = "phase2_enter"
            meta["mode"] = "phase2"
            meta["trail_dist_atr"] = coef
            meta["trail_distance"] = trail_dist
    else:
        candidate = new_highest - trail_dist
        if candidate > current_stop + 1e-12:
            event = "trail"
        new_stop = max(current_stop, candidate)
        meta["mode"] = "phase2"
        meta["trail_dist_atr"] = coef
        meta["trail_distance"] = trail_dist

    meta["event"] = event
    meta["step_count"] = meta.get("step_count", 0)
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
    p = profile_for_symbol(symbol)
    ov = _tier_overrides(_legacy, p)
    early_be = float(ov["early_breakeven_atr"] if ov["early_breakeven_atr"] is not None else p.early_breakeven_atr)
    step_adv_atr = float(ov["step_advance_atr"] if ov["step_advance_atr"] is not None else p.step_advance_atr)
    step_trig = float(ov["step_trigger_atr"] if ov["step_trigger_atr"] is not None else p.step_trigger_atr)
    arm_pct = ov["arm_tp1_pct"]
    cmin = ov["coef_min"]
    cmax = ov["coef_max"]

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
    tick = _price_tick(symbol)
    sr = float(smooth_ratio if smooth_ratio is not None else COLD_START_RATIO)

    new_lowest = min(lowest_price, price) if price > 0 else lowest_price
    if lowest_price <= 0 and price > 0:
        new_lowest = price
    new_stop = current_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {
        "mode": "phase2" if new_phase else "phase1",
        "breathing_coefficient": coef,
        "symbol_tag": p.symbol_tag,
    }

    step_advance = step_adv_atr * initial_atr
    arm_dist = effective_radar_arm_distance(
        initial_atr, sr, p, arm_tp1_pct=arm_pct, step_trigger_atr=step_trig,
    )
    arm_ratio = float(arm_pct) if arm_pct is not None else radar_start_ratio(sr, p)
    meta["radar_arm_ratio"] = arm_ratio
    meta["radar_arm_dist"] = arm_dist
    meta["arm_tp1_pct"] = arm_pct if arm_pct is not None else arm_ratio
    meta["step_trigger_atr"] = step_trig
    meta["early_breakeven_atr"] = early_be
    meta["step_advance_atr"] = step_adv_atr
    meta["coef_min"] = float(cmin if cmin is not None else p.coef_min)
    meta["coef_max"] = float(cmax if cmax is not None else p.coef_max)
    trail_dist = initial_atr * coef

    if not new_phase:
        move = max(0.0, entry_price - price) if price > 0 else 0.0
        if arm_dist <= 0 or move + 1e-12 < arm_dist:
            step_count = 0
            candidate = current_stop if current_stop > 0 else initial_stop
        else:
            extra = max(0.0, move - arm_dist)
            steps_after = (
                max(0, int(math.floor(extra / step_advance)))
                if step_advance > 0
                else 0
            )
            step_count = 1 + steps_after
            step_stop = initial_stop - step_count * step_advance
            candidate = min(current_stop, step_stop) if current_stop > 0 else step_stop
            if current_stop <= 0:
                candidate = step_stop
            if step_count > 0 and (current_stop <= 0 or candidate < current_stop - 1e-12):
                event = "step"
        meta["step_count"] = step_count

        if early_be > 0 and price <= entry_price - early_be * initial_atr:
            be = entry_price - tick
            if be < candidate:
                candidate = be
                event = "early_breakeven"

        if price <= entry_price - p.tp1_atr * initial_atr:
            floor = entry_price - p.tp1_floor_atr * initial_atr
            if floor < candidate:
                candidate = floor
                event = "floor_tp1"
        if price <= entry_price - p.tp2_atr * initial_atr:
            floor = entry_price - p.tp2_floor_atr * initial_atr
            if floor < candidate:
                candidate = floor
                event = "floor_tp2"

        new_stop = candidate

        if price <= entry_price - p.phase2_trigger_atr * initial_atr:
            new_phase = True
            trailed = new_lowest + trail_dist
            new_stop = min(new_stop, trailed)
            event = "phase2_enter"
            meta["mode"] = "phase2"
            meta["trail_dist_atr"] = coef
            meta["trail_distance"] = trail_dist
    else:
        candidate = new_lowest + trail_dist
        if current_stop <= 0 or candidate < current_stop - 1e-12:
            event = "trail"
        new_stop = min(current_stop, candidate) if current_stop > 0 else candidate
        meta["mode"] = "phase2"
        meta["trail_dist_atr"] = coef
        meta["trail_distance"] = trail_dist

    meta["event"] = event
    meta["step_count"] = meta.get("step_count", 0)
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
) -> dict[str, Any]:
    from app.core.breathing_profile import trail_distance_multiplier

    p = profile_for_symbol(symbol)
    sr = float(smooth_ratio if smooth_ratio is not None else COLD_START_RATIO)
    if coef_min is not None or coef_max is not None:
        cmin = float(coef_min if coef_min is not None else p.coef_min)
        cmax = float(coef_max if coef_max is not None else p.coef_max)
        # Progressive tier: remap ATR ratio onto this attempt's trail band
        coef = trail_distance_multiplier(sr, p, coef_min=cmin, coef_max=cmax)
    else:
        coef = resolve_breathing_coef(breathing_coefficient, symbol)
    side_u = str(side or "").upper()
    tier_kw = {
        "arm_tp1_pct": arm_tp1_pct,
        "step_trigger_atr": step_trigger_atr,
        "early_breakeven_atr": early_breakeven_atr,
        "step_advance_atr": step_advance_atr,
        "coef_min": coef_min,
        "coef_max": coef_max,
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
    p = profile_for_symbol(symbol)
    return (
        f"[{p.symbol_tag}] 初始{p.initial_sl_atr}ATR±{p.stop_order_buffer}"
        f" · 雷达启动=TP1×50/65/80/95递进/步进{p.step_advance_atr}×ATR"
        f" · 早保本{p.early_breakeven_atr}ATR"
        f" · 阶段二={p.phase2_trigger_atr}ATR"
        f" · 追踪{p.coef_min}~{p.coef_max}×ATR(连续插值)"
    )
