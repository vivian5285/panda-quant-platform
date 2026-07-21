"""VPS continuous-ladder radar — final checklist §四 (all exchanges).

State machine: activated + stepCount (monotonic; ATR refresh never rolls back steps).
Activate at 85% path to TP1 → BE.
Then: price ≥ entry+(stepCount+1)×0.5ATR → SL=entry+(stepCount+1)×0.3ATR; stepCount++.
TP1 floor ±0.5ATR · TP2 floor ±1.5ATR · TP3 trail peak±2.0ATR.
"""

from __future__ import annotations

from typing import Any

from app.core.radar_trail import (
    RADAR_ARM_PROGRESS,
    RADAR_LOCK_ATR,
    RADAR_STEP_ATR,
    RADAR_TP1_FLOOR_ATR,
    RADAR_TP2_FLOOR_ATR,
    RADAR_TP3_TRAIL_ATR,
    apply_radar_sl_direction,
    atr_floor_sl,
    breakeven_sl,
    favorable_move,
    resolve_atr,
    tp1_consumed,
    tp_path_progress,
)
from app.core.symbol_precision import round_price

RADAR_STAGE_LABELS: dict[int, str] = {
    0: "硬止损防守·雷达候命",
    1: "85%激活·保本",
    2: "阶梯跟进",
    3: "TP1底限",
    4: "TP2底限",
    5: "TP3动态追踪",
}

BREAKEVEN_BUFFER_PCT = 0.0003
ATR_REFRESH_SEC = 300.0
TP_LIMIT_TIMEOUT_SEC = 300.0


def tp1_filled_from_consumed(consumed_tp_levels: list | None) -> bool:
    if tp1_consumed(consumed_tp_levels):
        return True
    return any(int(x) in (2, 3) for x in (consumed_tp_levels or []))


def _reached_level(curr_px: float, level: float, side: str | None) -> bool:
    if level <= 0 or curr_px <= 0:
        return False
    if side == "LONG":
        return curr_px >= level
    if side == "SHORT":
        return curr_px <= level
    return False


def interval_path_progress(
    curr_px: float,
    start_px: float,
    end_px: float,
    side: str | None,
) -> float:
    curr_px = float(curr_px or 0)
    start_px = float(start_px or 0)
    end_px = float(end_px or 0)
    if curr_px <= 0 or start_px <= 0 or end_px <= 0:
        return 0.0
    if side == "LONG":
        span = end_px - start_px
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (curr_px - start_px) / span))
    if side == "SHORT":
        span = start_px - end_px
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (start_px - curr_px) / span))
    return 0.0


def stage_atr_mult(stage: int, trail_offset: float = RADAR_LOCK_ATR) -> float | None:
    if stage <= 0:
        return None
    if stage == 5:
        return float(RADAR_TP3_TRAIL_ATR)
    return float(trail_offset)


def detect_radar_stage(
    entry: float,
    curr_px: float,
    side: str | None,
    tp1: float,
    tp2: float,
    tp3: float,
    *,
    peak_px: float | None = None,
    tp1_filled: bool = False,
    regime: int = 3,
    move_step: float | None = None,
    armed: bool = False,
    step_count: int = 0,
) -> int:
    if not armed and not tp1_filled:
        return 0
    px = float(curr_px or 0)
    if _reached_level(px, tp3, side) or (
        peak_px and _reached_level(float(peak_px), tp3, side)
    ):
        return 5
    if _reached_level(px, tp2, side) or (
        peak_px and _reached_level(float(peak_px), tp2, side)
    ):
        return 4
    if _reached_level(px, tp1, side) or tp1_filled or (
        peak_px and _reached_level(float(peak_px), tp1, side)
    ):
        return 3
    if armed or tp_path_progress(entry, px, tp1, side) >= RADAR_ARM_PROGRESS:
        return 2 if int(step_count or 0) >= 1 else 1
    return 0


def is_favorable_radar_sl(old_sl: float, entry: float, side: str | None) -> bool:
    old_sl = float(old_sl or 0)
    entry = float(entry or 0)
    if old_sl <= 0 or entry <= 0:
        return False
    if side == "LONG":
        return old_sl > entry
    if side == "SHORT":
        return old_sl < entry
    return False


def compute_stage_radar_sl(
    stage: int,
    *,
    entry: float,
    best_price: float,
    atr: float,
    side: str | None,
    trail_offset: float = RADAR_LOCK_ATR,
) -> float:
    if stage <= 0:
        return 0.0
    if stage == 1:
        return breakeven_sl(entry, side)
    if stage == 5:
        a = max(float(atr or 0), 0.0)
        best = float(best_price or entry)
        if side == "LONG":
            return round_price(best - a * RADAR_TP3_TRAIL_ATR)
        if side == "SHORT":
            return round_price(best + a * RADAR_TP3_TRAIL_ATR)
        return 0.0
    if stage in (3, 4):
        mult = RADAR_TP1_FLOOR_ATR if stage == 3 else RADAR_TP2_FLOOR_ATR
        return atr_floor_sl(entry, atr, mult, side)
    return breakeven_sl(entry, side)


def _sl_at_step(entry: float, step_n: int, atr: float, side: str | None) -> float:
    """entry ± step_n × 0.3×ATR (step_n >= 1)."""
    if step_n <= 0 or entry <= 0:
        return 0.0
    delta = float(step_n) * max(float(atr or 0), 0.0) * RADAR_LOCK_ATR
    if side == "LONG":
        return round_price(entry + delta)
    if side == "SHORT":
        return round_price(entry - delta)
    return 0.0


def _next_step_trigger(entry: float, step_count: int, atr: float, side: str | None) -> float:
    """Price level for next step: entry ± (stepCount+1)×0.5×ATR."""
    n = int(step_count or 0) + 1
    delta = float(n) * max(float(atr or 0), 0.0) * RADAR_STEP_ATR
    if side == "LONG":
        return entry + delta
    if side == "SHORT":
        return entry - delta
    return 0.0


def compute_ladder_radar_sl(
    *,
    entry: float,
    curr_px: float,
    best_price: float,
    atr: float,
    side: str | None,
    tp1: float,
    tp2: float,
    tp3: float,
    activated: bool = False,
    step_count: int = 0,
) -> tuple[float, int, dict[str, Any]]:
    """
    Returns (raw_sl, stage, meta) where meta includes activated/step_count (monotonic).
    """
    entry = float(entry or 0)
    curr = float(curr_px or 0)
    best = float(best_price or curr or entry)
    a = resolve_atr(atr, entry)
    sc = max(int(step_count or 0), 0)
    act = bool(activated)
    meta: dict[str, Any] = {
        "slip_step": round(a * RADAR_STEP_ATR, 6),
        "follow_step": round(a * RADAR_LOCK_ATR, 6),
        "arm_progress": RADAR_ARM_PROGRESS,
        "atr": round(a, 4),
        "activated": act,
        "step_count": sc,
        "event": None,
    }
    if entry <= 0 or curr <= 0 or side not in ("LONG", "SHORT") or a <= 0:
        return 0.0, 0, meta

    progress = tp_path_progress(entry, curr, tp1, side)
    meta["tp1_progress"] = round(progress, 4)

    # TP3 dynamic trail
    if _reached_level(curr, tp3, side) or _reached_level(best, tp3, side):
        if side == "LONG":
            raw = round_price(best - a * RADAR_TP3_TRAIL_ATR)
        else:
            raw = round_price(best + a * RADAR_TP3_TRAIL_ATR)
        meta.update({"mode": "tp3_trail", "activated": True})
        return raw, 5, meta

    be = breakeven_sl(entry, side)

    # First activation at 85% path (or TP1 reached)
    if not act:
        if progress >= RADAR_ARM_PROGRESS or _reached_level(curr, tp1, side):
            act = True
            meta["activated"] = True
            meta["event"] = "radar_arm"
            meta["mode"] = "activate_be"
            raw = be
            # fall through to floors / step advances below
        else:
            return 0.0, 0, meta

    # Step advances: while price past next trigger, bump stepCount (monotonic)
    advanced = False
    for _ in range(32):  # safety bound
        trigger = _next_step_trigger(entry, sc, a, side)
        if trigger <= 0:
            break
        hit = (curr >= trigger) if side == "LONG" else (curr <= trigger)
        hit_peak = (best >= trigger) if side == "LONG" else (best <= trigger)
        if not (hit or hit_peak):
            break
        sc += 1
        advanced = True
    if advanced:
        meta["event"] = meta["event"] or "step_advance"
    meta["step_count"] = sc
    meta["activated"] = True

    raw = be
    if sc >= 1:
        ladder = _sl_at_step(entry, sc, a, side)
        if side == "LONG":
            raw = max(be, ladder)
        else:
            raw = min(be, ladder) if ladder > 0 else be

    # TP2 floor
    if _reached_level(curr, tp2, side) or _reached_level(best, tp2, side):
        floor = atr_floor_sl(entry, a, RADAR_TP2_FLOOR_ATR, side)
        if side == "LONG":
            raw = max(raw, floor)
        else:
            raw = min(raw, floor) if raw > 0 else floor
        meta.update({"mode": "tp2_floor", "floor": floor, "step_count": sc, "activated": True})
        return raw, 4, meta

    # TP1 floor
    if _reached_level(curr, tp1, side) or _reached_level(best, tp1, side):
        floor = atr_floor_sl(entry, a, RADAR_TP1_FLOOR_ATR, side)
        if side == "LONG":
            raw = max(raw, floor)
        else:
            raw = min(raw, floor) if raw > 0 else floor
        meta.update({"mode": "tp1_floor", "floor": floor, "step_count": sc, "activated": True})
        return raw, 3, meta

    stage = 2 if sc >= 1 else 1
    meta.update({"mode": "armed_ladder", "breakeven": be, "step_count": sc, "activated": True})
    return raw, stage, meta


def compute_vps_radar_sl(
    *,
    entry: float,
    curr_px: float,
    best_price: float,
    atr: float,
    side: str | None,
    tp1: float,
    tp2: float,
    tp3: float,
    old_sl: float,
    hard_sl: float,
    clamp_fn,
    radar_latched: bool = False,
    tp1_filled: bool = False,
    regime: int = 3,
    move_step: float | None = None,
    trail_offset: float | None = None,
    live_qty: float = 0.0,
    consumed_tp_levels: list | None = None,
    activated: bool = False,
    step_count: int = 0,
) -> dict[str, Any]:
    a = resolve_atr(atr, entry)
    progress = (
        round(tp_path_progress(entry, curr_px, tp1, side), 4) if tp1 > 0 else 0.0
    )
    filled = bool(tp1_filled or tp1_filled_from_consumed(consumed_tp_levels))
    act_in = bool(activated or radar_latched or filled)

    raw, stage, ladder_meta = compute_ladder_radar_sl(
        entry=entry,
        curr_px=curr_px,
        best_price=best_price,
        atr=a,
        side=side,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        activated=act_in,
        step_count=max(int(step_count or 0), 0),
    )
    act_out = bool(ladder_meta.get("activated"))
    sc_out = max(int(ladder_meta.get("step_count") or 0), int(step_count or 0))

    if not act_out and not filled:
        if radar_latched and is_favorable_radar_sl(old_sl, entry, side):
            return {
                "stage": 1,
                "stage_label": RADAR_STAGE_LABELS[1],
                "radar_sl": float(old_sl),
                "tp1_progress": progress,
                "armed": True,
                "activated": True,
                "step_count": sc_out,
                "latched_hold": True,
                "regime": int(regime),
                "move_step": RADAR_STEP_ATR,
                "trail_offset": RADAR_LOCK_ATR,
                "activation": RADAR_ARM_PROGRESS,
                "live_qty": float(live_qty or 0),
                "consumed_tp_levels": list(consumed_tp_levels or []),
                "event": None,
            }
        return {
            "stage": 0,
            "stage_label": RADAR_STAGE_LABELS[0],
            "radar_sl": 0.0,
            "tp1_progress": progress,
            "armed": False,
            "activated": False,
            "step_count": sc_out,
            "regime": int(regime),
            "move_step": RADAR_STEP_ATR,
            "trail_offset": RADAR_LOCK_ATR,
            "activation": RADAR_ARM_PROGRESS,
            "live_qty": float(live_qty or 0),
            "consumed_tp_levels": list(consumed_tp_levels or []),
            "event": None,
        }

    if filled and stage < 3:
        floor = atr_floor_sl(entry, a, RADAR_TP1_FLOOR_ATR, side)
        if floor > 0:
            raw = apply_radar_sl_direction(raw, floor, side) if raw > 0 else floor
            stage = max(stage, 3)

    if stage <= 0 or raw <= 0:
        raw = breakeven_sl(entry, side)
        stage = 1

    sl = clamp_fn(raw) if callable(clamp_fn) else raw
    sl = apply_radar_sl_direction(float(old_sl or 0), sl, side)
    if hard_sl > 0 and side == "LONG":
        sl = max(sl, hard_sl)
    elif hard_sl > 0 and side == "SHORT":
        sl = min(sl, hard_sl)

    return {
        "stage": stage,
        "stage_label": RADAR_STAGE_LABELS.get(stage, f"阶段{stage}"),
        "radar_sl": sl,
        "raw_sl": raw,
        "tp1_progress": progress,
        "armed": True,
        "activated": True,
        "step_count": sc_out,
        "latched": radar_latched or act_out,
        "tp1_filled": filled,
        "atr_mult": stage_atr_mult(stage),
        "regime": int(regime),
        "move_step": RADAR_STEP_ATR,
        "trail_offset": RADAR_LOCK_ATR,
        "activation": RADAR_ARM_PROGRESS,
        "live_qty": float(live_qty or 0),
        "consumed_tp_levels": list(consumed_tp_levels or []),
        "ladder": ladder_meta,
        "event": ladder_meta.get("event"),
    }


RADAR_STAGE_ATR_MULT: dict[int, float | None] = {
    1: None,
    2: RADAR_LOCK_ATR,
    3: RADAR_TP1_FLOOR_ATR,
    4: RADAR_TP2_FLOOR_ATR,
    5: RADAR_TP3_TRAIL_ATR,
}
