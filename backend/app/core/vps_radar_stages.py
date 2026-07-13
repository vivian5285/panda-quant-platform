"""VPS 8-stage radar trailing stop (v6.9.103 spec)."""

from __future__ import annotations

from typing import Any

from app.core.radar_trail import tp_path_progress
from app.core.symbol_precision import round_price

# Stage 0 = hard SL only (no radar)
RADAR_STAGE_LABELS: dict[int, str] = {
    0: "硬止损防守",
    1: "TP1路径70%·提前保本",
    2: "TP1路径85%·早追踪",
    3: "到达TP1·标准追踪",
    4: "TP1→TP2 25%",
    5: "TP1→TP2 50%",
    6: "TP1→TP2 75%",
    7: "到达TP2·深度锁利",
    8: "TP2→TP3 80%·极限保护",
}

RADAR_STAGE_ATR_MULT: dict[int, float | None] = {
    1: None,   # breakeven +0.1%
    2: 1.8,
    3: 1.2,
    4: 1.0,
    5: 0.8,
    6: 0.6,
    7: 0.5,
    8: 0.3,
}

BREAKEVEN_BUFFER_PCT = 0.001


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


def detect_radar_stage(
    entry: float,
    curr_px: float,
    side: str | None,
    tp1: float,
    tp2: float,
    tp3: float,
) -> int:
    """Highest stage reached by current price (0–8)."""
    if curr_px <= 0 or entry <= 0 or tp1 <= 0:
        return 0
    p_tp1 = tp_path_progress(entry, curr_px, tp1, side)
    if p_tp1 < 0.70:
        return 0
    if p_tp1 < 0.85:
        return 1
    if not _reached_level(curr_px, tp1, side):
        return 2
    if tp2 <= 0:
        return 3
    if not _reached_level(curr_px, tp2, side):
        p12 = interval_path_progress(curr_px, tp1, tp2, side)
        if p12 < 0.25:
            return 3
        if p12 < 0.50:
            return 4
        if p12 < 0.75:
            return 5
        return 6
    if tp3 <= 0:
        return 7
    p23 = interval_path_progress(curr_px, tp2, tp3, side)
    if p23 < 0.80:
        return 7
    return 8


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
) -> dict[str, Any]:
    """Full radar evaluation: stage detect → SL compute → floor → direction."""
    stage = detect_radar_stage(entry, curr_px, side, tp1, tp2, tp3)
    raw = compute_stage_radar_sl(
        stage, entry=entry, best_price=best_price, atr=atr, side=side,
    )
    if stage <= 0 or raw <= 0:
        return {
            "stage": 0,
            "stage_label": RADAR_STAGE_LABELS[0],
            "radar_sl": 0.0,
            "tp1_progress": round(tp_path_progress(entry, curr_px, tp1, side), 4) if tp1 > 0 else 0.0,
            "armed": False,
        }

    sl = clamp_fn(raw)
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
        "tp1_progress": round(tp_path_progress(entry, curr_px, tp1, side), 4) if tp1 > 0 else 0.0,
        "armed": True,
        "atr_mult": RADAR_STAGE_ATR_MULT.get(stage),
    }
