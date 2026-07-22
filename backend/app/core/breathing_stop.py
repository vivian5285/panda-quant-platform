"""Breathing stop — shared engine; ETH/XAU differ only via breathing_profile.

Phase 1: early breakeven + ATR step ladder × breathing_coefficient
Phase 2: trail = initial_atr × coef × trail_tighten
initial_atr from TV webhook atr; coef from Binance 1h ATR ratio.
"""

from __future__ import annotations

import math
from typing import Any

from app.core.breathing_profile import (
    ETH_PROFILE,
    get_breathing_coefficient_for_profile,
    profile_for_symbol,
    resolve_coef,
)
from app.core.symbol_registry import symbol_meta

# Module-level defaults = ETH (back-compat for imports/tests)
INITIAL_SL_ATR = ETH_PROFILE.initial_sl_atr
STEP_TRIGGER_ATR = ETH_PROFILE.step_trigger_atr
STEP_ADVANCE_ATR = ETH_PROFILE.step_advance_atr
BREAKEVEN_TRIGGER_ATR = ETH_PROFILE.phase2_trigger_atr
TP1_ATR = ETH_PROFILE.tp1_atr
TP1_FLOOR_ATR = ETH_PROFILE.tp1_floor_atr
TP2_ATR = ETH_PROFILE.tp2_atr
TP2_FLOOR_ATR = ETH_PROFILE.tp2_floor_atr
TP3_ATR = ETH_PROFILE.tp3_atr
DEFAULT_ATR = 30.0
DEFAULT_BREATHING_COEF = 1.0
STOP_ORDER_BUFFER_USDT = ETH_PROFILE.stop_order_buffer

ADX_WEAK_BOUND = 15.0
ADX_STRONG_BOUND = 35.0
TRAIL_DIST_WEAK_ATR = 1.2
TRAIL_DIST_STRONG_ATR = 2.5
DEFAULT_ADX = 25.0


def get_breathing_coefficient(smooth_ratio: float, symbol: str | None = None) -> float:
    return get_breathing_coefficient_for_profile(
        smooth_ratio, profile_for_symbol(symbol),
    )


def resolve_breathing_coef(coef: float | None, symbol: str | None = None) -> float:
    return resolve_coef(coef, profile_for_symbol(symbol))


def trail_distance_by_adx(adx_val: float) -> float:
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


def compute_initial_stop(
    entry: float,
    side: str,
    atr: float,
    symbol: str | None = None,
) -> float:
    """Logical initial stop (no exchange buffer)."""
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
    coef = resolve_coef(breathing_coefficient, p)
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
    **_legacy: Any,
) -> tuple[float, float, bool, dict[str, Any]]:
    p = profile_for_symbol(symbol)
    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = resolve_atr(initial_atr)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    highest_price = float(highest_price or entry_price or 0)
    coef = resolve_coef(breathing_coefficient, p)
    tick = _price_tick(symbol)

    new_highest = max(highest_price, price) if price > 0 else highest_price
    new_stop = current_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {
        "mode": "phase2" if new_phase else "phase1",
        "breathing_coefficient": coef,
        "symbol_tag": p.symbol_tag,
    }

    step_trigger = p.step_trigger_atr * initial_atr * coef
    step_advance = p.step_advance_atr * initial_atr * coef
    trail_dist = initial_atr * coef * p.trail_tighten

    if not new_phase:
        step_count = (
            max(0, int(math.floor((price - entry_price) / step_trigger)))
            if step_trigger > 0 and price > 0
            else 0
        )
        step_stop = initial_stop + step_count * step_advance
        candidate = max(current_stop, step_stop)
        if step_count > 0 and candidate > current_stop + 1e-12:
            event = "step"
        meta["step_count"] = step_count

        # Early breakeven → entry + 1 tick
        if p.early_breakeven_atr > 0 and price >= entry_price + p.early_breakeven_atr * initial_atr:
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
            meta["trail_dist_atr"] = coef * p.trail_tighten
            meta["trail_distance"] = trail_dist
    else:
        candidate = new_highest - trail_dist
        if candidate > current_stop + 1e-12:
            event = "trail"
        new_stop = max(current_stop, candidate)
        meta["mode"] = "phase2"
        meta["trail_dist_atr"] = coef * p.trail_tighten
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
    **_legacy: Any,
) -> tuple[float, float, bool, dict[str, Any]]:
    p = profile_for_symbol(symbol)
    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = resolve_atr(initial_atr)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    lowest_price = float(lowest_price or entry_price or 0)
    coef = resolve_coef(breathing_coefficient, p)
    tick = _price_tick(symbol)

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

    step_trigger = p.step_trigger_atr * initial_atr * coef
    step_advance = p.step_advance_atr * initial_atr * coef
    trail_dist = initial_atr * coef * p.trail_tighten

    if not new_phase:
        step_count = (
            max(0, int(math.floor((entry_price - price) / step_trigger)))
            if step_trigger > 0 and price > 0
            else 0
        )
        step_stop = initial_stop - step_count * step_advance
        candidate = min(current_stop, step_stop) if current_stop > 0 else step_stop
        if current_stop <= 0:
            candidate = step_stop
        if step_count > 0 and (current_stop <= 0 or candidate < current_stop - 1e-12):
            event = "step"
        meta["step_count"] = step_count

        if p.early_breakeven_atr > 0 and price <= entry_price - p.early_breakeven_atr * initial_atr:
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
            meta["trail_dist_atr"] = coef * p.trail_tighten
            meta["trail_distance"] = trail_dist
    else:
        candidate = new_lowest + trail_dist
        if current_stop <= 0 or candidate < current_stop - 1e-12:
            event = "trail"
        new_stop = min(current_stop, candidate) if current_stop > 0 else candidate
        meta["mode"] = "phase2"
        meta["trail_dist_atr"] = coef * p.trail_tighten
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
) -> dict[str, Any]:
    coef = resolve_breathing_coef(breathing_coefficient, symbol)
    side_u = str(side or "").upper()
    if side_u == "LONG":
        new_stop, peak, phase, meta = calculate_stop_long(
            price, entry_price, initial_atr, initial_stop,
            current_stop, best_price, breakeven_phase, coef, symbol=symbol,
        )
    elif side_u == "SHORT":
        new_stop, peak, phase, meta = calculate_stop_short(
            price, entry_price, initial_atr, initial_stop,
            current_stop, best_price, breakeven_phase, coef, symbol=symbol,
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
        f" · 步进{p.step_trigger_atr}/{p.step_advance_atr}×呼吸"
        f" · 早保本{p.early_breakeven_atr}ATR"
        f" · 阶段二={p.phase2_trigger_atr}ATR"
        f" · 追踪×{p.trail_tighten}"
    )
