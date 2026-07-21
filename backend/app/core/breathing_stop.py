"""Breathing stop — merged hard SL + radar (all exchanges).

Two-phase state machine (TV stop_loss NEVER used as exchange stop price):
  Phase 1: ATR step ladder from initial_stop (entry ± 1.5×ATR)
  Phase 2: ADX-driven continuous trail after +3.0×ATR float

initial_atr / initial_stop are fixed at open. TV price/stop_loss are sizing-only
(see tv_entry_sizing adjust_coef) and must not feed tick-level stop math.
"""

from __future__ import annotations

import math
from typing import Any

INITIAL_SL_ATR = 1.5
STEP_TRIGGER_ATR = 0.75
STEP_ADVANCE_ATR = 0.4
BREAKEVEN_TRIGGER_ATR = 3.0
TP1_ATR = 1.35
TP1_FLOOR_ATR = 0.5
TP2_ATR = 2.5
TP2_FLOOR_ATR = 1.5

ADX_WEAK_BOUND = 15.0
ADX_STRONG_BOUND = 35.0
TRAIL_DIST_WEAK_ATR = 1.2
TRAIL_DIST_STRONG_ATR = 2.5
DEFAULT_ADX = 25.0  # mid of 15–35 when TV omits adx
DEFAULT_ATR = 30.0


def trail_distance_by_adx(adx_val: float) -> float:
    """Linear interpolate trail distance (×ATR) from ADX strength."""
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


def compute_initial_stop(entry: float, side: str, atr: float) -> float:
    entry = float(entry or 0)
    atr = resolve_atr(atr)
    if entry <= 0:
        return 0.0
    if side == "LONG":
        return entry - INITIAL_SL_ATR * atr
    if side == "SHORT":
        return entry + INITIAL_SL_ATR * atr
    return 0.0


def init_breathing_state(
    entry: float,
    side: str,
    atr: float | None = None,
    adx: float | None = None,
) -> dict[str, Any]:
    """Initial persisted fields for one position."""
    atr_v = resolve_atr(atr)
    adx_v = resolve_adx(adx)
    entry_v = float(entry or 0)
    stop = compute_initial_stop(entry_v, side, atr_v)
    return {
        "entry_price": entry_v,
        "initial_atr": atr_v,
        "initial_stop": stop,
        "current_sl": stop,
        "best_price": entry_v,
        "breakeven_phase": False,
        "current_adx": adx_v,
        "remaining_qty_pct": 1.0,
        "side": side,
    }


def calculate_stop_long(
    price: float,
    entry_price: float,
    initial_atr: float,
    initial_stop: float,
    current_stop: float,
    highest_price: float,
    breakeven_phase: bool,
    adx_val: float,
) -> tuple[float, float, bool, dict[str, Any]]:
    """LONG breathing stop. Returns (new_stop, new_highest, new_phase, meta)."""
    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = resolve_atr(initial_atr)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    highest_price = float(highest_price or entry_price or 0)
    adx_val = resolve_adx(adx_val)

    new_highest = max(highest_price, price) if price > 0 else highest_price
    new_stop = current_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {"mode": "phase2" if new_phase else "phase1", "adx": adx_val}

    if not new_phase:
        step_count = max(
            0, int(math.floor((price - entry_price) / (STEP_TRIGGER_ATR * initial_atr)))
        ) if initial_atr > 0 and price > 0 else 0
        step_stop = initial_stop + step_count * STEP_ADVANCE_ATR * initial_atr
        candidate = max(current_stop, step_stop)
        if step_count > 0 and candidate > current_stop + 1e-12:
            event = "step"
        meta["step_count"] = step_count

        if price >= entry_price + TP1_ATR * initial_atr:
            floor = entry_price + TP1_FLOOR_ATR * initial_atr
            if floor > candidate:
                candidate = floor
                event = "floor_tp1"
        if price >= entry_price + TP2_ATR * initial_atr:
            floor = entry_price + TP2_FLOOR_ATR * initial_atr
            if floor > candidate:
                candidate = floor
                event = "floor_tp2"

        new_stop = candidate

        if price >= entry_price + BREAKEVEN_TRIGGER_ATR * initial_atr:
            new_phase = True
            trail_dist = trail_distance_by_adx(adx_val) * initial_atr
            trailed = new_highest - trail_dist
            new_stop = max(new_stop, trailed)
            event = "phase2_enter"
            meta["mode"] = "phase2"
            meta["trail_dist_atr"] = trail_distance_by_adx(adx_val)
    else:
        trail_dist = trail_distance_by_adx(adx_val) * initial_atr
        candidate = new_highest - trail_dist
        if candidate > current_stop + 1e-12:
            event = "trail"
        new_stop = max(current_stop, candidate)
        meta["mode"] = "phase2"
        meta["trail_dist_atr"] = trail_distance_by_adx(adx_val)

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
    adx_val: float,
) -> tuple[float, float, bool, dict[str, Any]]:
    """SHORT breathing stop. Returns (new_stop, new_lowest, new_phase, meta)."""
    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = resolve_atr(initial_atr)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    lowest_price = float(lowest_price or entry_price or 0)
    adx_val = resolve_adx(adx_val)

    new_lowest = min(lowest_price, price) if price > 0 else lowest_price
    if lowest_price <= 0 and price > 0:
        new_lowest = price
    new_stop = current_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {"mode": "phase2" if new_phase else "phase1", "adx": adx_val}

    if not new_phase:
        step_count = max(
            0, int(math.floor((entry_price - price) / (STEP_TRIGGER_ATR * initial_atr)))
        ) if initial_atr > 0 and price > 0 else 0
        step_stop = initial_stop - step_count * STEP_ADVANCE_ATR * initial_atr
        candidate = min(current_stop, step_stop) if current_stop > 0 else step_stop
        if current_stop <= 0:
            candidate = step_stop
        if step_count > 0 and (current_stop <= 0 or candidate < current_stop - 1e-12):
            event = "step"
        meta["step_count"] = step_count

        if price <= entry_price - TP1_ATR * initial_atr:
            floor = entry_price - TP1_FLOOR_ATR * initial_atr
            if floor < candidate:
                candidate = floor
                event = "floor_tp1"
        if price <= entry_price - TP2_ATR * initial_atr:
            floor = entry_price - TP2_FLOOR_ATR * initial_atr
            if floor < candidate:
                candidate = floor
                event = "floor_tp2"

        new_stop = candidate

        if price <= entry_price - BREAKEVEN_TRIGGER_ATR * initial_atr:
            new_phase = True
            trail_dist = trail_distance_by_adx(adx_val) * initial_atr
            trailed = new_lowest + trail_dist
            new_stop = min(new_stop, trailed)
            event = "phase2_enter"
            meta["mode"] = "phase2"
            meta["trail_dist_atr"] = trail_distance_by_adx(adx_val)
    else:
        trail_dist = trail_distance_by_adx(adx_val) * initial_atr
        candidate = new_lowest + trail_dist
        if current_stop <= 0 or candidate < current_stop - 1e-12:
            event = "trail"
        new_stop = min(current_stop, candidate) if current_stop > 0 else candidate
        meta["mode"] = "phase2"
        meta["trail_dist_atr"] = trail_distance_by_adx(adx_val)

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
    adx_val: float | None = None,
) -> dict[str, Any]:
    """One tick evaluation. Returns unified result dict."""
    adx = resolve_adx(adx_val)
    side_u = str(side or "").upper()
    if side_u == "LONG":
        new_stop, peak, phase, meta = calculate_stop_long(
            price, entry_price, initial_atr, initial_stop,
            current_stop, best_price, breakeven_phase, adx,
        )
    elif side_u == "SHORT":
        new_stop, peak, phase, meta = calculate_stop_short(
            price, entry_price, initial_atr, initial_stop,
            current_stop, best_price, breakeven_phase, adx,
        )
    else:
        return {
            "current_sl": float(current_stop or 0),
            "best_price": float(best_price or 0),
            "breakeven_phase": bool(breakeven_phase),
            "event": "none",
            "improved": False,
            "meta": {},
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
        "adx": adx,
        "meta": meta,
        "initial_atr": resolve_atr(initial_atr),
        "initial_stop": float(initial_stop or 0),
    }


def stop_hit(side: str | None, price: float, current_stop: float) -> bool:
    """True when mark crosses the breathing stop."""
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


def format_breathing_legend() -> str:
    return (
        f"初始{INITIAL_SL_ATR}ATR"
        f" · 步进{STEP_TRIGGER_ATR}/{STEP_ADVANCE_ATR}ATR"
        f" · 保本触发{BREAKEVEN_TRIGGER_ATR}ATR"
        f" · ADX追踪{TRAIL_DIST_WEAK_ATR}–{TRAIL_DIST_STRONG_ATR}ATR"
    )
