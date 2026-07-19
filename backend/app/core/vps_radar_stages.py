"""VPS radar trailing — regime arm + move_step stages + ATR breath (all exchanges).

Single engine used by PositionSupervisor / Deepcoin / AdverseRadarMixin.
Do NOT invent a parallel trail ratio table elsewhere.
"""

from __future__ import annotations

from typing import Any

from app.core.radar_trail import (
    regime_radar_move_step,
    regime_radar_row,
    regime_radar_trail_offset,
    tp1_consumed,
    tp_path_progress,
)
from app.core.symbol_precision import round_price

# Stage 0 = VPS hard SL only (before path arm / TP fill)
RADAR_STAGE_LABELS: dict[int, str] = {
    0: "硬止损防守",
    1: "路径达激活·保本",
    2: "TP1→TP2 步进·追踪",
    3: "到达TP2·锁利",
    4: "TP2→TP3 步进·加深",
    5: "到达TP3·极限保护",
}

BREAKEVEN_BUFFER_PCT = 0.001

# After breakeven: gentle tighten of breath ATR as stages advance (宁松勿紧)
_STAGE_BREATH_FACTOR: dict[int, float] = {
    2: 1.00,
    3: 0.85,
    4: 0.75,
    5: 0.60,
}


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
    """0 at start_px, 1 at end_px along favorable direction."""
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


def stage_atr_mult(stage: int, trail_offset: float) -> float | None:
    """Breathing ATR for trail stages; stage 1 = breakeven (no ATR trail)."""
    if stage <= 1:
        return None
    factor = _STAGE_BREATH_FACTOR.get(int(stage), 1.0)
    return max(0.15, float(trail_offset) * factor)


def _detect_radar_stage_at_px(
    entry: float,
    px: float,
    side: str | None,
    tp1: float,
    tp2: float,
    tp3: float,
    *,
    armed: bool,
    move_step: float,
) -> int:
    """Stage once armed. Interval advance uses regime move_step (not fixed 50%)."""
    if not armed or entry <= 0:
        return 0
    if px <= 0:
        return 1

    step = max(0.10, min(0.50, float(move_step or 0.25)))

    if tp1 > 0 and not _reached_level(px, tp1, side):
        return 1

    stage = 1
    if tp2 <= 0:
        return stage
    if not _reached_level(px, tp2, side):
        if interval_path_progress(px, tp1, tp2, side) >= step:
            return 2
        return 1

    stage = 3
    if tp3 <= 0:
        return stage
    if not _reached_level(px, tp3, side):
        if interval_path_progress(px, tp2, tp3, side) >= step:
            return 4
        return 3
    return 5


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
) -> int:
    """Highest stage (0–5). Peak preserves stage on pullback."""
    armed = bool(tp1_filled)
    step = float(move_step) if move_step is not None else regime_radar_move_step(regime)
    stage = _detect_radar_stage_at_px(
        entry, curr_px, side, tp1, tp2, tp3, armed=armed, move_step=step,
    )
    if peak_px is not None and float(peak_px or 0) > 0 and armed:
        peak_stage = _detect_radar_stage_at_px(
            entry, float(peak_px), side, tp1, tp2, tp3, armed=True, move_step=step,
        )
        stage = max(stage, peak_stage)
    return stage


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
    trail_offset: float = 0.65,
) -> float:
    """Raw radar SL for stage (before hard-stop floor / direction clamp)."""
    if stage <= 0:
        return 0.0
    entry = float(entry or 0)
    best = float(best_price or entry)
    a = max(float(atr or 0), 0.0)

    if stage == 1:
        if side == "LONG":
            return round_price(entry * (1.0 + BREAKEVEN_BUFFER_PCT))
        if side == "SHORT":
            return round_price(entry * (1.0 - BREAKEVEN_BUFFER_PCT))
        return round_price(entry)

    mult = stage_atr_mult(stage, trail_offset)
    if mult is None or a <= 0:
        return 0.0
    if side == "LONG":
        return round_price(best - a * mult)
    if side == "SHORT":
        return round_price(best + a * mult)
    return 0.0


def apply_radar_sl_direction(old_sl: float, new_sl: float, side: str | None) -> float:
    """SL only moves favorably: up for LONG, down for SHORT."""
    if new_sl <= 0:
        return old_sl
    if side == "LONG":
        if old_sl <= 0:
            return new_sl
        return max(float(old_sl), float(new_sl))
    if side == "SHORT":
        if old_sl <= 0:
            return new_sl
        return min(float(old_sl), float(new_sl))
    return new_sl


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
) -> dict[str, Any]:
    """
    Full radar evaluation (single authority).
    Arms when path activation / TP fill / latched.
    Stage never retreats on pullback. Hard SL is floor only.
    TP123 limits share no STOP slot — radar only updates the stop slot.
    """
    row = regime_radar_row(regime)
    step = float(move_step) if move_step is not None else float(row["move_step"])
    breath = float(trail_offset) if trail_offset is not None else float(row["trail_offset"])

    armed_gate = bool(tp1_filled or radar_latched)
    if radar_latched and is_favorable_radar_sl(old_sl, entry, side):
        armed_gate = True
    # TP fill evidence from consumed (caller should sync with price+book first)
    if tp1_filled_from_consumed(consumed_tp_levels):
        armed_gate = True

    peak_px = best_price if armed_gate else None
    stage = detect_radar_stage(
        entry, curr_px, side, tp1, tp2, tp3,
        peak_px=peak_px,
        tp1_filled=armed_gate,
        regime=regime,
        move_step=step,
    )
    if armed_gate and stage <= 0:
        stage = 1

    raw = compute_stage_radar_sl(
        stage,
        entry=entry,
        best_price=best_price,
        atr=atr,
        side=side,
        trail_offset=breath,
    )
    progress = (
        round(tp_path_progress(entry, curr_px, tp1, side), 4) if tp1 > 0 else 0.0
    )
    atr_mult = stage_atr_mult(stage, breath)

    if stage <= 0 or raw <= 0:
        if radar_latched and is_favorable_radar_sl(old_sl, entry, side):
            return {
                "stage": 1,
                "stage_label": RADAR_STAGE_LABELS[1],
                "radar_sl": float(old_sl),
                "tp1_progress": progress,
                "armed": True,
                "latched_hold": True,
                "regime": int(regime),
                "move_step": step,
                "trail_offset": breath,
                "live_qty": float(live_qty or 0),
                "consumed_tp_levels": list(consumed_tp_levels or []),
            }
        return {
            "stage": 0,
            "stage_label": RADAR_STAGE_LABELS[0],
            "radar_sl": 0.0,
            "tp1_progress": progress,
            "armed": False,
            "regime": int(regime),
            "move_step": step,
            "trail_offset": breath,
            "live_qty": float(live_qty or 0),
            "consumed_tp_levels": list(consumed_tp_levels or []),
        }

    sl = clamp_fn(raw)
    sl = apply_radar_sl_direction(float(old_sl or 0), sl, side)
    # Hard SL is floor only — never lets radar retreat wider than VPS hard stop
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
        "latched": radar_latched,
        "tp1_filled": tp1_filled or tp1_filled_from_consumed(consumed_tp_levels),
        "atr_mult": atr_mult,
        "regime": int(regime),
        "move_step": step,
        "trail_offset": breath,
        "activation": float(row["activation"]),
        "live_qty": float(live_qty or 0),
        "consumed_tp_levels": list(consumed_tp_levels or []),
    }


# Deprecated alias — old code imported RADAR_STAGE_ATR_MULT; keep empty to surface misuse
RADAR_STAGE_ATR_MULT: dict[int, float | None] = {
    1: None,
    2: None,
    3: None,
    4: None,
    5: None,
}
