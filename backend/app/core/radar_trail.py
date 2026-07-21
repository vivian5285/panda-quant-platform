"""Radar continuous ladder trailing — v6.5.6 (all exchanges).

Activate at 85% path to TP1 → breakeven.
Then every +0.5×ATR favorable move → raise SL by +0.3×ATR.
Milestone floors: TP1 → entry+0.5ATR; TP2 → entry+1.5ATR;
TP3 → pure trail peak−2.0ATR (only favorable).

Old REGIME_RADAR 50/60/70/80 path tables REMOVED.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.symbol_precision import round_price

# --- v6.5.6 continuous ladder params (single source) ---
RADAR_ARM_PROGRESS = 0.85
RADAR_STEP_ATR = 0.50
RADAR_LOCK_ATR = 0.30
RADAR_TP1_FLOOR_ATR = 0.50
RADAR_TP2_FLOOR_ATR = 1.50
RADAR_TP3_TRAIL_ATR = 2.00
RADAR_BREAKEVEN_TICK_PCT = 0.0003  # ~1 tick slack past entry
DEFAULT_ATR_ETH = 12.0  # when TV omits atr (ETH 10~15 pts)

# Compat aliases — all regimes share the same ladder (regime key inert)
REGIME_RADAR: dict[int, dict[str, float]] = {
    r: {
        "activation": RADAR_ARM_PROGRESS,
        "move_step": RADAR_STEP_ATR,
        "trail_offset": RADAR_LOCK_ATR,
    }
    for r in (1, 2, 3, 4)
}

RADAR_PRE_TP1_ARM_PROGRESS = RADAR_ARM_PROGRESS
RADAR_STARTUP_PROFIT_PROGRESS = RADAR_ARM_PROGRESS
RADAR_OPEN_GRACE_SEC = 15.0
RADAR_ARM_CONFIRM_POLLS = 2
RADAR_MIN_TRAIL_TP1_FRAC = 0.18
FEE_BUFFER_PCT = 0.0015
RADAR_BREAKEVEN_ATR_BEFORE_TP1 = 0.55
RADAR_BREAKEVEN_ATR_AFTER_TP1 = 0.25
RADAR_TIGHT_SPAN_ATR_MULT = 1.0
RADAR_TIGHT_SPAN_MIN_PROGRESS = 0.85
RADAR_MIN_ABS_ATR_MULT = 0.30
RADAR_MIN_ABS_ENTRY_PCT = 0.0010
RADAR_EFFECTIVE_CAP = 0.98


def clamp_regime_id(regime: int) -> int:
    r = int(regime or 3)
    if r < 1:
        return 1
    if r > 4:
        return 4
    return r


def regime_radar_row(regime: int = 3) -> dict[str, float]:
    return dict(REGIME_RADAR[clamp_regime_id(regime)])


def merge_regime_radar(base: dict[int, dict]) -> dict[int, dict]:
    merged: dict[int, dict] = {}
    for r, cfg in base.items():
        row = dict(cfg)
        row.update(REGIME_RADAR.get(int(r), REGIME_RADAR[3]))
        merged[int(r)] = row
    return merged


def regime_radar_activation(regime: int = 3) -> float:
    return float(RADAR_ARM_PROGRESS)


def regime_radar_move_step(regime: int = 3) -> float:
    return float(RADAR_STEP_ATR)


def regime_radar_trail_offset(regime: int = 3) -> float:
    return float(RADAR_LOCK_ATR)


def resolve_atr(atr: float, entry: float = 0.0, symbol: str | None = None) -> float:
    a = float(atr or 0)
    if a > 0:
        return a
    return float(DEFAULT_ATR_ETH)


def tp1_distance(entry: float, tv_tps: list, atr: float) -> float:
    if tv_tps and float(tv_tps[0] or 0) > 0:
        return abs(float(tv_tps[0]) - float(entry))
    return max(float(atr or 0) * 1.5, 1.0)


def trail_distance(atr: float, trail_mult: float, tp1_dist: float) -> float:
    atr_dist = max(float(atr or 0), 0.0) * max(float(trail_mult or 0), 0.0)
    min_dist = max(float(tp1_dist or 0) * RADAR_MIN_TRAIL_TP1_FRAC, 0.0)
    return max(atr_dist, min_dist)


def tp1_consumed(consumed_tp_levels: list | None) -> bool:
    return 1 in (consumed_tp_levels or [])


def tp_path_progress(
    entry: float,
    curr_px: float,
    tp1: float,
    side: str | None,
) -> float:
    entry = float(entry or 0)
    tp1 = float(tp1 or 0)
    curr_px = float(curr_px or 0)
    if entry <= 0 or tp1 <= 0 or curr_px <= 0:
        return 0.0
    if side == "LONG":
        span = tp1 - entry
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (curr_px - entry) / span))
    if side == "SHORT":
        span = entry - tp1
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (entry - curr_px) / span))
    return 0.0


def radar_arm_trigger_price(
    entry: float,
    tp1: float,
    side: str | None,
    progress: float = RADAR_ARM_PROGRESS,
) -> float:
    """Arm price at `progress` along entry→TP1 (checklist §四 / §九).

    Doc shorthand:
      LONG  ``tp1 × 0.85``  → path 85% to TP1 (NOT literal multiply)
      SHORT ``tp1 × 1.15``  → 「tp1 上方 15%」= path 85% toward TP1
        i.e. ``tp1 + (1-progress)×(entry-tp1)``
    """
    entry = float(entry or 0)
    tp1 = float(tp1 or 0)
    p = max(0.0, min(1.0, float(progress if progress is not None else RADAR_ARM_PROGRESS)))
    if entry <= 0 or tp1 <= 0:
        return 0.0
    if side == "LONG":
        span = tp1 - entry
        if span <= 0:
            return 0.0
        return entry + p * span
    if side == "SHORT":
        span = entry - tp1
        if span <= 0:
            return 0.0
        # 85% toward TP1 == 15% of span above TP1
        return tp1 + (1.0 - p) * span
    return 0.0


def favorable_move(entry: float, curr_px: float, side: str | None) -> float:
    entry = float(entry or 0)
    curr_px = float(curr_px or 0)
    if entry <= 0 or curr_px <= 0:
        return 0.0
    if side == "LONG":
        return max(0.0, curr_px - entry)
    if side == "SHORT":
        return max(0.0, entry - curr_px)
    return 0.0


def radar_min_absolute_move(entry: float, atr: float) -> float:
    atr_floor = max(float(atr or 0), 0.0) * RADAR_MIN_ABS_ATR_MULT
    pct_floor = abs(float(entry or 0)) * RADAR_MIN_ABS_ENTRY_PCT
    return max(atr_floor, pct_floor)


def radar_effective_activation(
    regime: int,
    entry: float,
    tp1: float,
    atr: float,
) -> float:
    """Fixed 85% arm (regime ignored)."""
    return float(RADAR_ARM_PROGRESS)


def _reached(curr_px: float, level: float, side: str | None) -> bool:
    if level <= 0 or curr_px <= 0:
        return False
    if side == "LONG":
        return curr_px >= level
    if side == "SHORT":
        return curr_px <= level
    return False


def evaluate_radar_arm_gate(
    *,
    consumed_tp_levels: list | None,
    progress: float,
    regime: int,
    entry: float,
    tp1: float,
    atr: float,
    curr_px: float,
    side: str | None,
    trade_opened_at: float | None = None,
    path_ok_streak: int = 0,
    now_ts: float | None = None,
    radar_latched: bool = False,
) -> dict[str, Any]:
    """
    Arm when path ≥ 85% to TP1, or TP1 filled / latched.
    Open grace + confirm polls kept as noise guards.
    """
    now = float(now_ts if now_ts is not None else time.time())
    base_act = RADAR_ARM_PROGRESS
    eff_act = RADAR_ARM_PROGRESS
    move = favorable_move(entry, curr_px, side)
    min_abs = radar_min_absolute_move(entry, atr)
    span = abs(float(tp1 or 0) - float(entry or 0)) if entry and tp1 else 0.0

    if radar_latched:
        return {
            "should_arm": True,
            "reason": "already_latched",
            "base_activation": base_act,
            "effective_activation": eff_act,
            "progress": float(progress or 0),
            "path_ok_streak": int(path_ok_streak or 0),
            "confirm_needed": RADAR_ARM_CONFIRM_POLLS,
            "open_grace_sec": RADAR_OPEN_GRACE_SEC,
        }

    if tp1_consumed(consumed_tp_levels) or any(
        int(x) in (1, 2, 3) for x in (consumed_tp_levels or [])
    ):
        return {
            "should_arm": True,
            "reason": "tp_filled",
            "base_activation": base_act,
            "effective_activation": eff_act,
            "progress": float(progress or 0),
            "path_ok_streak": int(path_ok_streak or 0),
            "confirm_needed": RADAR_ARM_CONFIRM_POLLS,
            "open_grace_sec": RADAR_OPEN_GRACE_SEC,
        }

    if trade_opened_at and (now - float(trade_opened_at)) < RADAR_OPEN_GRACE_SEC:
        return {
            "should_arm": False,
            "reason": "open_grace",
            "base_activation": base_act,
            "effective_activation": eff_act,
            "progress": float(progress or 0),
            "path_ok_streak": 0,
            "confirm_needed": RADAR_ARM_CONFIRM_POLLS,
            "open_grace_sec": RADAR_OPEN_GRACE_SEC,
        }

    path_ok = float(progress or 0) >= eff_act and (
        min_abs <= 0 or move + 1e-12 >= min_abs or span <= 0
    )
    if _reached(curr_px, tp1, side):
        path_ok = True

    streak = int(path_ok_streak or 0) + 1 if path_ok else 0
    should = path_ok and streak >= RADAR_ARM_CONFIRM_POLLS
    return {
        "should_arm": should,
        "reason": "path_arm" if should else ("path_wait" if path_ok else "path_low"),
        "base_activation": base_act,
        "effective_activation": eff_act,
        "progress": float(progress or 0),
        "path_ok_streak": streak,
        "confirm_needed": RADAR_ARM_CONFIRM_POLLS,
        "open_grace_sec": RADAR_OPEN_GRACE_SEC,
        "favorable_move": round(move, 4),
        "min_abs_move": round(min_abs, 4),
    }


def breakeven_sl(entry: float, side: str | None) -> float:
    entry = float(entry or 0)
    if entry <= 0:
        return 0.0
    tick = entry * RADAR_BREAKEVEN_TICK_PCT
    if side == "LONG":
        return round_price(entry + max(tick, 0.01))
    if side == "SHORT":
        return round_price(entry - max(tick, 0.01))
    return round_price(entry)


def atr_floor_sl(entry: float, atr: float, mult: float, side: str | None) -> float:
    entry = float(entry or 0)
    a = max(float(atr or 0), 0.0)
    if entry <= 0 or a <= 0:
        return 0.0
    delta = a * float(mult)
    if side == "LONG":
        return round_price(entry + delta)
    if side == "SHORT":
        return round_price(entry - delta)
    return 0.0


def steps_from_move(move: float, atr: float) -> int:
    step = max(float(atr or 0) * RADAR_STEP_ATR, 1e-9)
    if move <= 0:
        return 0
    return int(move // step)


def ladder_raise_from(base_sl: float, steps: int, atr: float, side: str | None) -> float:
    if steps <= 0 or base_sl <= 0:
        return float(base_sl or 0)
    delta = float(steps) * max(float(atr or 0), 0.0) * RADAR_LOCK_ATR
    if side == "LONG":
        return round_price(base_sl + delta)
    if side == "SHORT":
        return round_price(base_sl - delta)
    return float(base_sl)


def apply_radar_sl_direction(old_sl: float, new_sl: float, side: str | None) -> float:
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


def radar_may_arm(
    *,
    consumed_tp_levels: list | None,
    progress: float,
    activation_ratio: float,
    radar_active: bool = False,
    regime: int | None = None,
    entry: float = 0.0,
    tp1: float = 0.0,
    atr: float = 0.0,
    curr_px: float = 0.0,
    side: str | None = None,
    trade_opened_at: float | None = None,
    path_ok_streak: int = 0,
    now_ts: float | None = None,
) -> bool:
    if radar_active:
        return True
    if regime is not None and entry > 0 and tp1 > 0:
        decision = evaluate_radar_arm_gate(
            consumed_tp_levels=consumed_tp_levels,
            progress=progress,
            regime=int(regime),
            entry=entry,
            tp1=tp1,
            atr=atr,
            curr_px=curr_px or entry,
            side=side,
            trade_opened_at=trade_opened_at,
            path_ok_streak=path_ok_streak,
            now_ts=now_ts,
            radar_latched=False,
        )
        return bool(decision.get("arm"))
    if tp1_consumed(consumed_tp_levels):
        return True
    if any(int(x) in (2, 3) for x in (consumed_tp_levels or [])):
        return True
    act = max(float(activation_ratio or 0), 0.0)
    if act > 0 and float(progress or 0) >= act - 1e-9:
        return True
    return False


def breakeven_floor(
    entry: float,
    side: str | None,
    atr: float,
    *,
    consumed_tp_levels: list | None = None,
) -> float:
    fee = float(entry) * FEE_BUFFER_PCT
    atr_mult = (
        RADAR_BREAKEVEN_ATR_AFTER_TP1
        if tp1_consumed(consumed_tp_levels)
        else RADAR_BREAKEVEN_ATR_BEFORE_TP1
    )
    slack = max(fee, float(atr or 0) * atr_mult)
    if side == "LONG":
        return round_price(float(entry) + slack)
    if side == "SHORT":
        return round_price(float(entry) - slack)
    return round_price(float(entry))


STOP_MARKET_MIN_GAP_USD = 1.0
STOP_MARKET_MIN_GAP_PCT = 0.0008


def stop_market_min_gap(curr_px: float) -> float:
    if curr_px <= 0:
        return STOP_MARKET_MIN_GAP_USD
    return max(STOP_MARKET_MIN_GAP_USD, float(curr_px) * STOP_MARKET_MIN_GAP_PCT)


def clamp_stop_market_safe(sl: float, curr_px: float, side: str | None) -> float:
    """Keep STOP trigger strictly on the safe side of mark — avoids instant full close."""
    if sl <= 0 or curr_px <= 0:
        return sl
    gap = stop_market_min_gap(curr_px)
    if side == "LONG":
        return round_price(min(float(sl), float(curr_px) - gap))
    if side == "SHORT":
        return round_price(max(float(sl), float(curr_px) + gap))
    return round_price(float(sl))


def stop_would_trigger_immediately(sl: float, curr_px: float, side: str | None) -> bool:
    if sl <= 0 or curr_px <= 0:
        return False
    safe = clamp_stop_market_safe(sl, curr_px, side)
    if side == "LONG":
        return safe < sl - 1e-9
    if side == "SHORT":
        return safe > sl + 1e-9
    return False


def compute_radar_sl(
    *,
    side: str | None,
    entry: float,
    best_price: float,
    atr: float,
    trail_mult: float,
    tp1_dist: float,
    consumed_tp_levels: list | None,
    clamp_fn,
    trail_cap_px: float | None = None,
) -> float:
    """Legacy helper for unit tests — live path uses compute_vps_radar_sl only."""
    trail = trail_distance(atr, trail_mult, tp1_dist)
    floor = clamp_fn(
        breakeven_floor(entry, side, atr, consumed_tp_levels=consumed_tp_levels)
    )
    if side == "LONG":
        sl = round_price(max(float(best_price) - trail, floor))
        if trail_cap_px and trail_cap_px > entry:
            sl = min(sl, round_price(float(trail_cap_px) * 0.995))
        return sl
    if side == "SHORT":
        sl = round_price(min(float(best_price) + trail, floor))
        if trail_cap_px and 0 < trail_cap_px < entry:
            sl = max(sl, round_price(float(trail_cap_px) * 1.005))
        return sl
    return 0.0
