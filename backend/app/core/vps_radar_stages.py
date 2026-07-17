"""VPS radar trailing stop — path-to-TP1 arming + 5-stage trail (all regimes)."""

from __future__ import annotations

from typing import Any

from app.core.radar_trail import tp1_consumed, tp_path_progress
from app.core.symbol_precision import round_price

# Stage 0 = VPS hard SL only (before TP1 fill — breathing room)
RADAR_STAGE_LABELS: dict[int, str] = {
    0: "硬止损防守",
    1: "路径达激活·保本",
    2: "TP1→TP2 50%·追踪",
    3: "到达TP2·锁利",
    4: "TP2→TP3 50%·加深",
    5: "到达TP3·极限保护",
}

# Stage 1 = breakeven ±0.1%; later stages = ATR trail from best price
RADAR_STAGE_ATR_MULT: dict[int, float | None] = {
    1: None,
    2: 1.0,
    3: 0.6,
    4: 0.5,
    5: 0.3,
}

BREAKEVEN_BUFFER_PCT = 0.001


def tp1_filled_from_consumed(consumed_tp_levels: list | None) -> bool:
    """TP1 fill (or later TP fills that imply TP1 already took)."""
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


def _detect_radar_stage_at_px(
    entry: float,
    px: float,
    side: str | None,
    tp1: float,
    tp2: float,
    tp3: float,
    *,
    armed: bool,
) -> int:
    """Stage once armed (path activation or TP fill). Before TP1 mark → stage 1 only."""
    if not armed or entry <= 0:
        return 0
    if px <= 0:
        return 1

    if tp1 > 0 and not _reached_level(px, tp1, side):
        return 1

    stage = 1
    if tp2 <= 0:
        return stage
    if not _reached_level(px, tp2, side):
        if interval_path_progress(px, tp1, tp2, side) >= 0.50:
            return 2
        return 1

    stage = 3
    if tp3 <= 0:
        return stage
    if not _reached_level(px, tp3, side):
        if interval_path_progress(px, tp2, tp3, side) >= 0.50:
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
) -> int:
    """Highest stage (0–5). tp1_filled means armed (path or fill); peak preserves stage."""
    armed = bool(tp1_filled)
    stage = _detect_radar_stage_at_px(
        entry, curr_px, side, tp1, tp2, tp3, armed=armed,
    )
    if peak_px is not None and float(peak_px or 0) > 0 and armed:
        peak_stage = _detect_radar_stage_at_px(
            entry, float(peak_px), side, tp1, tp2, tp3, armed=True,
        )
        stage = max(stage, peak_stage)
    return stage


def is_favorable_radar_sl(old_sl: float, entry: float, side: str | None) -> bool:
    """True when old_sl is a locked profit / breakeven stop (not the wide hard SL)."""
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

    mult = RADAR_STAGE_ATR_MULT.get(stage)
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
) -> dict[str, Any]:
    """
    Full radar evaluation.
    Arms when path-to-TP1 activation is reached (or TP filled / latched).
    Stage never retreats on pullback. Hard SL is floor only.
    """
    armed_gate = bool(tp1_filled or radar_latched)
    if radar_latched and is_favorable_radar_sl(old_sl, entry, side):
        armed_gate = True

    peak_px = best_price if armed_gate else None
    stage = detect_radar_stage(
        entry, curr_px, side, tp1, tp2, tp3,
        peak_px=peak_px, tp1_filled=armed_gate,
    )
    if armed_gate and stage <= 0:
        stage = 1

    raw = compute_stage_radar_sl(
        stage, entry=entry, best_price=best_price, atr=atr, side=side,
    )
    progress = (
        round(tp_path_progress(entry, curr_px, tp1, side), 4) if tp1 > 0 else 0.0
    )

    if stage <= 0 or raw <= 0:
        if radar_latched and is_favorable_radar_sl(old_sl, entry, side):
            return {
                "stage": 1,
                "stage_label": RADAR_STAGE_LABELS[1],
                "radar_sl": float(old_sl),
                "tp1_progress": progress,
                "armed": True,
                "latched_hold": True,
            }
        return {
            "stage": 0,
            "stage_label": RADAR_STAGE_LABELS[0],
            "radar_sl": 0.0,
            "tp1_progress": progress,
            "armed": False,
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
        "tp1_filled": tp1_filled,
        "atr_mult": RADAR_STAGE_ATR_MULT.get(stage),
    }
