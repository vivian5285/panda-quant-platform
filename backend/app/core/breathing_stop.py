"""Breathing stop — merged hard SL + radar (all exchanges).

Two-phase state machine (TV stop_loss NEVER used as exchange stop price):
  Phase 1: ATR step ladder from initial_stop (entry ± 1.5×ATR), scaled by breathing coef
  Phase 2: adaptive trail after +3.0×ATR float (trail = initial_atr × breathing_coefficient)

initial_atr is frozen at open from TV webhook ``atr``.
Breathing coefficient is driven by Binance native 1h ATR / initial_atr (smoothed).
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
# TP3 price is reference-only (phase-2 remainder); never hung as a limit.
TP3_ATR = 4.0

DEFAULT_ATR = 30.0
DEFAULT_BREATHING_COEF = 1.0
STOP_ORDER_BUFFER_USDT = 0.3

# Legacy ADX constants kept for import compat / old tests; LIVE path no longer uses them.
ADX_WEAK_BOUND = 15.0
ADX_STRONG_BOUND = 35.0
TRAIL_DIST_WEAK_ATR = 1.2
TRAIL_DIST_STRONG_ATR = 2.5
DEFAULT_ADX = 25.0


def get_breathing_coefficient(smooth_ratio: float) -> float:
    """Map smoothed (atr_1h / initial_atr) to breathing coefficient 0.7–1.5."""
    r = float(smooth_ratio or 0)
    if r <= 0:
        return DEFAULT_BREATHING_COEF
    if r < 0.7:
        return 0.7
    if r < 1.0:
        return 0.85
    if r < 1.4:
        return 1.0
    if r < 2.0:
        # 1.4→1.2 … 2.0→1.4 linear
        return 1.2 + (r - 1.4) / 0.6 * 0.2
    return 1.5


def resolve_breathing_coef(coef: float | None) -> float:
    try:
        c = float(coef if coef is not None else DEFAULT_BREATHING_COEF)
    except (TypeError, ValueError):
        return DEFAULT_BREATHING_COEF
    if c <= 0:
        return DEFAULT_BREATHING_COEF
    return max(0.7, min(1.5, c))


def trail_distance_by_adx(adx_val: float) -> float:
    """Deprecated — LIVE uses breathing_coefficient. Kept for legacy imports."""
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
    """Deprecated ADX resolver — kept for mixin soft-refresh compat."""
    try:
        a = float(adx if adx is not None else DEFAULT_ADX)
    except (TypeError, ValueError):
        return DEFAULT_ADX
    return a if a > 0 else DEFAULT_ADX


def compute_initial_stop(entry: float, side: str, atr: float) -> float:
    """Logical initial stop (no exchange buffer)."""
    entry = float(entry or 0)
    atr = resolve_atr(atr)
    if entry <= 0:
        return 0.0
    if side == "LONG":
        return entry - INITIAL_SL_ATR * atr
    if side == "SHORT":
        return entry + INITIAL_SL_ATR * atr
    return 0.0


def apply_stop_order_buffer(side: str | None, stop: float) -> float:
    """Exchange hang price: LONG −0.3 / SHORT +0.3 USDT execution buffer."""
    sl = float(stop or 0)
    if sl <= 0:
        return 0.0
    side_u = str(side or "").upper()
    if side_u == "LONG":
        return sl - STOP_ORDER_BUFFER_USDT
    if side_u == "SHORT":
        return sl + STOP_ORDER_BUFFER_USDT
    return sl


def compute_tp_ladder_from_atr(
    entry: float,
    side: str,
    atr: float | None = None,
) -> list[float]:
    """Market-derived TP1/TP2/TP3 prices for external/manual adopt (no TV history).

    Only TP1+TP2 are placeable as limits; TP3 is kept for phase-2 remainder math.
    """
    entry_v = float(entry or 0)
    atr_v = resolve_atr(atr)
    side_u = str(side or "").upper()
    if entry_v <= 0 or side_u not in ("LONG", "SHORT"):
        return [0.0, 0.0, 0.0]
    sign = 1.0 if side_u == "LONG" else -1.0
    return [
        entry_v + sign * TP1_ATR * atr_v,
        entry_v + sign * TP2_ATR * atr_v,
        entry_v + sign * TP3_ATR * atr_v,
    ]


def init_breathing_state(
    entry: float,
    side: str,
    atr: float | None = None,
    breathing_coefficient: float | None = None,
    **_legacy: Any,
) -> dict[str, Any]:
    """Initial persisted fields for one position."""
    atr_v = resolve_atr(atr)
    coef = resolve_breathing_coef(breathing_coefficient)
    # Accept legacy adx= kwarg without using it
    if breathing_coefficient is None and _legacy.get("adx") is not None:
        coef = DEFAULT_BREATHING_COEF
    entry_v = float(entry or 0)
    stop = compute_initial_stop(entry_v, side, atr_v)
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
        # Compat for older state readers
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
    **_legacy: Any,
) -> tuple[float, float, bool, dict[str, Any]]:
    """LONG breathing stop. Returns (new_stop, new_highest, new_phase, meta)."""
    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = resolve_atr(initial_atr)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    highest_price = float(highest_price or entry_price or 0)
    # Legacy positional/kw: 8th arg used to be adx_val
    if "adx_val" in _legacy and breathing_coefficient == DEFAULT_BREATHING_COEF:
        # Old call style passed adx as 8th positional — already mapped if named
        pass
    coef = resolve_breathing_coef(breathing_coefficient)

    new_highest = max(highest_price, price) if price > 0 else highest_price
    new_stop = current_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {
        "mode": "phase2" if new_phase else "phase1",
        "breathing_coefficient": coef,
    }

    step_trigger = STEP_TRIGGER_ATR * initial_atr * coef
    step_advance = STEP_ADVANCE_ATR * initial_atr * coef
    trail_dist = initial_atr * coef

    if not new_phase:
        step_count = max(
            0, int(math.floor((price - entry_price) / step_trigger))
        ) if step_trigger > 0 and price > 0 else 0
        step_stop = initial_stop + step_count * step_advance
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
    **_legacy: Any,
) -> tuple[float, float, bool, dict[str, Any]]:
    """SHORT breathing stop. Returns (new_stop, new_lowest, new_phase, meta)."""
    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = resolve_atr(initial_atr)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    lowest_price = float(lowest_price or entry_price or 0)
    coef = resolve_breathing_coef(breathing_coefficient)

    new_lowest = min(lowest_price, price) if price > 0 else lowest_price
    if lowest_price <= 0 and price > 0:
        new_lowest = price
    new_stop = current_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {
        "mode": "phase2" if new_phase else "phase1",
        "breathing_coefficient": coef,
    }

    step_trigger = STEP_TRIGGER_ATR * initial_atr * coef
    step_advance = STEP_ADVANCE_ATR * initial_atr * coef
    trail_dist = initial_atr * coef

    if not new_phase:
        step_count = max(
            0, int(math.floor((entry_price - price) / step_trigger))
        ) if step_trigger > 0 and price > 0 else 0
        step_stop = initial_stop - step_count * step_advance
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
) -> dict[str, Any]:
    """One tick evaluation. Returns unified result dict."""
    # Prefer explicit breathing_coefficient; ignore adx_val for LIVE math
    coef = resolve_breathing_coef(
        breathing_coefficient if breathing_coefficient is not None else DEFAULT_BREATHING_COEF
    )
    side_u = str(side or "").upper()
    if side_u == "LONG":
        new_stop, peak, phase, meta = calculate_stop_long(
            price, entry_price, initial_atr, initial_stop,
            current_stop, best_price, breakeven_phase, coef,
        )
    elif side_u == "SHORT":
        new_stop, peak, phase, meta = calculate_stop_short(
            price, entry_price, initial_atr, initial_stop,
            current_stop, best_price, breakeven_phase, coef,
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
        "adx": resolve_adx(adx_val),  # compat only
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
        f" · 步进{STEP_TRIGGER_ATR}/{STEP_ADVANCE_ATR}ATR×呼吸系数"
        f" · 保本触发{BREAKEVEN_TRIGGER_ATR}ATR"
        f" · 追踪=ATR×呼吸系数(0.7–1.5)"
        f" · 挂单缓冲±{STOP_ORDER_BUFFER_USDT}"
    )
