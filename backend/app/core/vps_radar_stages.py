"""Radar stage labels + helpers — LIVE SL is breathing_stop (final spec).

Old continuous-ladder SL math is purged. Calling purged calculators raises RuntimeError.
Radar arm: absolute price anchor only (Spec §6.1).
"""

from __future__ import annotations

from typing import Any

from app.core.radar_trail import (
    apply_radar_sl_direction,
    tp1_consumed,
)
from app.core.trend_tier_params import (
    radar_armed_by_absolute_price,
)

RADAR_STAGE_LABELS: dict[int, str] = {
    0: "硬止损防守·雷达候命",
    1: "绝对价格锚定·保本",
    2: "雷达激活·步进跟踪",
    3: "TP1区间",
    4: "TP2区间",
    5: "TP3动态追踪",
}

BREAKEVEN_BUFFER_PCT = 0.0003
ATR_REFRESH_SEC = 300.0
TP_LIMIT_TIMEOUT_SEC = 300.0

_LEGACY_PURGE_MSG = (
    "LEGACY_PURGED: old radar SL math removed. "
    "LIVE path = breathing_stop.apply_breathing_tick "
    "(arm=absolute_price_anchor Spec §6.1)."
)


def tp1_filled_from_consumed(consumed_tp_levels: list | None) -> bool:
    """Spec §6.1: full TP1 fill required for forced radar activation on recovery.

    TP1 partial fill does NOT trigger forced activation.
    TP2-only fill does NOT trigger forced activation.
    """
    return tp1_consumed(consumed_tp_levels)


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
    is_reentry: bool = False,
) -> int:
    """Alert/metadata stage only — never drives stop placement.

    Spec §6.1: radar arms on absolute price anchor.
    """
    del regime, move_step  # unused; kept for call-site compat
    px = float(curr_px or 0)

    # TP-zone reach (informational only)
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

    # Absolute price anchor arm check (Spec §6.1)
    if armed or radar_armed_by_absolute_price(
        side=str(side or ""),
        price=px,
        tp1=float(tp1 or 0),
        tp2=float(tp2 or 0),
        is_reentry=is_reentry,
    ):
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


def _purge_ladder(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError(_LEGACY_PURGE_MSG)


# Physical purge of §14 items — old ladder SL authority
compute_stage_radar_sl = _purge_ladder
compute_ladder_radar_sl = _purge_ladder
compute_vps_radar_sl = _purge_ladder

__all__ = [
    "ATR_REFRESH_SEC",
    "BREAKEVEN_BUFFER_PCT",
    "RADAR_STAGE_LABELS",
    "TP_LIMIT_TIMEOUT_SEC",
    "apply_radar_sl_direction",
    "compute_ladder_radar_sl",
    "compute_stage_radar_sl",
    "compute_vps_radar_sl",
    "detect_radar_stage",
    "interval_path_progress",
    "is_favorable_radar_sl",
    "tp1_filled_from_consumed",
]
