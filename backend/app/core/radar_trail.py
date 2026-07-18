"""Radar breakeven trailing — path-to-TP1 activation by regime, then ATR stages."""

from __future__ import annotations

import time
from typing import Any

from app.core.symbol_precision import round_price

# Min trail width as fraction of entry→TP1 (avoids ATR-only tight stops on ETH)
RADAR_MIN_TRAIL_TP1_FRAC = 0.22
FEE_BUFFER_PCT = 0.0015
# Breakeven floor slack (ATR) — wider before TP1, tighter after TP1 lock-in
RADAR_BREAKEVEN_ATR_BEFORE_TP1 = 0.55
RADAR_BREAKEVEN_ATR_AFTER_TP1 = 0.25

# Compat aliases — unified path arm at 85% (15% remaining to TP1)
RADAR_PRE_TP1_ARM_PROGRESS = 0.85
RADAR_STARTUP_PROFIT_PROGRESS = 0.85

# Path-to-TP1 arming (primary gate — all regimes same):
# 距 TP1 还剩 15%（进度 ≥ 85%）即启动保本，继续追踪锁住 TP2/TP3 利润
REGIME_RADAR: dict[int, dict[str, float]] = {
    1: {"activation": 0.85, "trail_offset": 0.75},
    2: {"activation": 0.85, "trail_offset": 1.00},
    3: {"activation": 0.85, "trail_offset": 1.35},
    4: {"activation": 0.85, "trail_offset": 1.80},
}

# Global arm guards (all exchanges) — prevent noise on tight TV TP1 spans
RADAR_OPEN_GRACE_SEC = 25.0
RADAR_ARM_CONFIRM_POLLS = 2
# When entry→TP1 span < 1.0×ATR, raise required progress (still ≤ 92%)
RADAR_TIGHT_SPAN_ATR_MULT = 1.0
RADAR_TIGHT_SPAN_MIN_PROGRESS = 0.92
# Absolute favorable-move floor so 85% of a tiny span cannot arm on a tick
RADAR_MIN_ABS_ATR_MULT = 0.55
RADAR_MIN_ABS_ENTRY_PCT = 0.0015  # 0.15% of entry
RADAR_EFFECTIVE_CAP = 0.98


def merge_regime_radar(base: dict[int, dict]) -> dict[int, dict]:
    """Overlay radar params onto margin/ratios regime_settings."""
    merged: dict[int, dict] = {}
    for r, cfg in base.items():
        row = dict(cfg)
        row.update(REGIME_RADAR.get(int(r), {}))
        merged[int(r)] = row
    return merged


def regime_radar_activation(regime: int) -> float:
    """TP1 path fraction required to arm radar for this regime."""
    r = int(regime or 3)
    if r < 1:
        r = 1
    if r > 4:
        r = 4
    return float(REGIME_RADAR[r]["activation"])


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
    """0→1 progress from entry toward TP1 (used for radar arming and trail pacing)."""
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
    """Minimum favorable mark move (USD) before path-arm is allowed."""
    atr_floor = max(float(atr or 0), 0.0) * RADAR_MIN_ABS_ATR_MULT
    pct_floor = abs(float(entry or 0)) * RADAR_MIN_ABS_ENTRY_PCT
    return max(atr_floor, pct_floor)


def radar_effective_activation(
    regime: int,
    entry: float,
    tp1: float,
    atr: float,
) -> float:
    """
    Regime path ratio raised when TV TP1 span is tight vs ATR / absolute floor.

    Base = 85% (15% remaining to TP1). Tight spans raise toward ~92%, never block
    a healthy absolute move once progress already meets the raised floor.
    """
    base = regime_radar_activation(regime)
    entry = float(entry or 0)
    tp1 = float(tp1 or 0)
    atr_v = max(float(atr or 0), 0.0)
    if entry <= 0 or tp1 <= 0:
        return 1.0
    span = abs(tp1 - entry)
    if span <= 0:
        return 1.0
    eff = base
    if atr_v > 0 and span < atr_v * RADAR_TIGHT_SPAN_ATR_MULT:
        eff = max(eff, RADAR_TIGHT_SPAN_MIN_PROGRESS)
    min_abs = radar_min_absolute_move(entry, atr_v)
    if min_abs > 0:
        needed = min_abs / span
        if needed > eff:
            eff = min(RADAR_EFFECTIVE_CAP, needed)
    return float(eff)


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
    Full arm decision for all exchanges.

    Returns ok/arm meta used by supervisors + DingTalk.
    - TP fill / later TP → arm immediately (no grace/confirm)
    - Path arm → open grace + effective activation + confirm polls
    - Already latched → keep trailing (caller decides clear-premature)
    """
    now = float(now_ts if now_ts is not None else time.time())
    base_act = regime_radar_activation(regime)
    eff_act = radar_effective_activation(regime, entry, tp1, atr)
    move = favorable_move(entry, curr_px, side)
    min_abs = radar_min_absolute_move(entry, atr)
    span = abs(float(tp1 or 0) - float(entry or 0)) if entry and tp1 else 0.0
    age = None
    if trade_opened_at and float(trade_opened_at) > 0:
        age = max(0.0, now - float(trade_opened_at))

    meta: dict[str, Any] = {
        "progress": round(float(progress or 0), 4),
        "activation_base": base_act,
        "activation_effective": round(eff_act, 4),
        "favorable_move": round(move, 4),
        "min_abs_move": round(min_abs, 4),
        "tp1_span": round(span, 4),
        "open_age_sec": round(age, 1) if age is not None else None,
        "path_ok_streak": int(path_ok_streak or 0),
        "arm_reason": None,
        "ok": False,
        "arm": False,
        "building_confirm": False,
        "blocked_grace": False,
        "blocked_abs": False,
    }

    if radar_latched:
        meta["ok"] = True
        meta["arm"] = True
        meta["arm_reason"] = "latched"
        return meta

    if tp1_consumed(consumed_tp_levels):
        meta["ok"] = True
        meta["arm"] = True
        meta["arm_reason"] = "tp1_filled"
        return meta
    if any(int(x) in (2, 3) for x in (consumed_tp_levels or [])):
        meta["ok"] = True
        meta["arm"] = True
        meta["arm_reason"] = "tp23_filled"
        return meta

    if age is not None and age < RADAR_OPEN_GRACE_SEC:
        meta["blocked_grace"] = True
        meta["arm_reason"] = "open_grace"
        meta["path_ok_streak"] = 0
        return meta

    prog = float(progress or 0)
    if prog + 1e-9 < eff_act:
        meta["arm_reason"] = "path_below_effective"
        meta["path_ok_streak"] = 0
        return meta

    if move + 1e-9 < min_abs:
        meta["blocked_abs"] = True
        meta["arm_reason"] = "abs_move_below_floor"
        meta["path_ok_streak"] = 0
        return meta

    streak = int(path_ok_streak or 0) + 1
    meta["path_ok_streak"] = streak
    meta["ok"] = True
    if streak < RADAR_ARM_CONFIRM_POLLS:
        meta["building_confirm"] = True
        meta["arm_reason"] = "confirming"
        meta["arm"] = False
        return meta

    meta["arm"] = True
    meta["arm_reason"] = "path_effective"
    return meta


def radar_may_arm(
    *,
    consumed_tp_levels: list | None,
    progress: float,
    activation_ratio: float,
    radar_active: bool = False,
    # Optional global guards (preferred for live supervisors)
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
    """
    When to place/move breakeven radar STOP:
    - already armed and trailing
    - path to TP1 ≥ 85% (15% remaining — primary; tight-span may raise effective)
    - TP1+ filled (qty/book still used for slice accounting, not required to arm)

    When entry/tp1/atr provided, applies tight-span effective activation + open grace + confirm.
    """
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
    """True when a closePosition STOP would fire as soon as it hits the book."""
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
