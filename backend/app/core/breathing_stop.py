"""Breathing stop — shared engine; ETH/XAU/BNB differ only via breathing_profile.

Spec v3 (final):
  - ATR source: always TV webhook (VPS does not independently fetch/calculate ATR)
  - Radar arm: absolute price anchor (Spec §6.1):
      First open: (TP1 + TP2) / 2
      Reentry: TP2
  - Early breakeven checkpoint: TP1 distance × 0.5 (Spec §6.0)
  - Breathing coefficient: continuous interpolation from TV ATR (no ADX bands)
  - Hard stop buffer: FIXED 1.15 (not tiered)
  - TP1 + TP2: limit orders. TP3: never (radar-only 70%)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from app.core.breathing_profile import (
    BNB_PROFILE,
    ETH_PROFILE,
    cold_start_multiplier,
    get_breathing_coefficient_for_profile,
    profile_for_symbol,
    resolve_coef,
    COLD_START_RATIO,
)
from app.core.symbol_registry import symbol_meta

# Module-level defaults = ETH (back-compat for imports/tests)
INITIAL_SL_ATR = ETH_PROFILE.initial_sl_atr
STEP_ADVANCE_ATR = ETH_PROFILE.step_advance_atr
TP1_ATR = ETH_PROFILE.tp1_atr
DEFAULT_ATR = 30.0
DEFAULT_BREATHING_COEF = cold_start_multiplier(ETH_PROFILE)
STOP_ORDER_BUFFER_USDT = ETH_PROFILE.stop_order_buffer

HARD_STOP_MIN_TICKS = 5

TEMP_TV_STOP_BUFFER = 1.15  # whitepaper v3 fixed breathing pad (not tiered)
# Deprecated — retained for compat imports only
HARD_VS_RADAR_FLOOR = 1.05
HARD_SLIP_MULT = 0.0


def get_breathing_coefficient(smooth_ratio: float, symbol: str | None = None) -> float:
    return get_breathing_coefficient_for_profile(
        smooth_ratio, profile_for_symbol(symbol),
    )


def resolve_breathing_coef(coef: float | None, symbol: str | None = None) -> float:
    return resolve_coef(coef, profile_for_symbol(symbol))


def default_breathing_coef(symbol: str | None = None) -> float:
    return cold_start_multiplier(profile_for_symbol(symbol))


def load_breathing_coef(raw: Any, symbol: str | None = None) -> float:
    """State load: missing/non-positive → cold-start; else keep value (tick clamps)."""
    if raw is None:
        return default_breathing_coef(symbol)
    try:
        c = float(raw)
    except (TypeError, ValueError):
        return default_breathing_coef(symbol)
    if c != c or c <= 0:
        return default_breathing_coef(symbol)
    return c


def resolve_atr(atr: float | None) -> float:
    a = float(atr or 0)
    return a if a > 0 else DEFAULT_ATR


def _price_tick(symbol: str | None) -> float:
    try:
        meta = symbol_meta(symbol) if symbol else {}
        tick = float(meta.get("price_tick") or 0.01)
        return tick if tick > 0 else 0.01
    except Exception:
        return 0.01


def hard_stop_buffer_mult(
    symbol: str | None = None,
    *,
    trend_tier: int | None = None,
) -> float:
    """Whitepaper v3: fixed 1.15 for ETH/XAU all tiers."""
    _ = (symbol, trend_tier)
    try:
        from app.core.trend_tier_params import HARD_STOP_BUFFER_FIXED
        from app.config import get_settings

        s = get_settings()
        return float(
            getattr(s, "HARD_STOP_BUFFER_MULT", None)
            or HARD_STOP_BUFFER_FIXED
            or TEMP_TV_STOP_BUFFER
        )
    except Exception:
        return float(TEMP_TV_STOP_BUFFER)


def hard_stop_min_ticks(symbol: str | None = None) -> int:
    try:
        from app.config import get_settings

        return int(getattr(get_settings(), "HARD_STOP_MIN_TICKS", HARD_STOP_MIN_TICKS) or HARD_STOP_MIN_TICKS)
    except Exception:
        return int(HARD_STOP_MIN_TICKS)


def compute_initial_stop(
    entry: float,
    side: str,
    atr: float,
    symbol: str | None = None,
) -> float:
    """Logical radar initial stop (no exchange buffer)."""
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


def compute_hard_stop_distance(
    *,
    fill_entry: float,
    tv_stop_loss: float,
    tv_entry: float | None = None,
    initial_atr: float | None = None,
    symbol: str | None = None,
    slip_mult: float | None = None,
    buffer_mult: float | None = None,
    trend_tier: int | None = None,
) -> dict[str, float]:
    """Hard-stop distance from TV (whitepaper v3).

    tv_stop_distance = |TV.price − TV.stop_loss|
    actual = tv_stop_distance × 1.15 (fixed; not ADX-tiered)
    Hang = fill ± actual (no ATR floor, no fill-slip pad).
    """
    fill = float(fill_entry or 0)
    tv_sl = float(tv_stop_loss or 0)
    tv_e = float(tv_entry or 0) or fill
    buf = float(
        buffer_mult
        if buffer_mult is not None
        else hard_stop_buffer_mult(symbol, trend_tier=trend_tier)
    )
    if buf <= 0:
        buf = float(TEMP_TV_STOP_BUFFER)
    out = {
        "tv_stop_distance": 0.0,
        "tv_implied_dist": 0.0,
        "base_dist": 0.0,
        "final_dist": 0.0,
        "fill_entry": fill,
        "tv_entry": tv_e,
        "buffer_mult": buf,
        "min_ticks": float(hard_stop_min_ticks(symbol)),
        "tick": float(_price_tick(symbol)),
        "reject_reason": "",
    }
    if fill <= 0 or tv_sl <= 0 or tv_e <= 0:
        out["reject_reason"] = "missing_tv_stop_or_entry"
        return out
    raw = abs(tv_e - tv_sl)
    out["tv_stop_distance"] = raw
    tick = float(out["tick"] or 0.01)
    min_ticks = int(out["min_ticks"] or HARD_STOP_MIN_TICKS)
    if raw + 1e-12 < tick * max(1, min_ticks):
        out["reject_reason"] = "tv_stop_distance_too_small"
        return out
    actual = raw * buf
    out["tv_implied_dist"] = actual
    out["base_dist"] = actual
    out["final_dist"] = actual
    return out


def compute_temp_tv_stop(
    entry: float,
    side: str,
    tv_stop_loss: float,
    *,
    tv_entry: float | None = None,
    initial_atr: float | None = None,
    symbol: str | None = None,
    slip_mult: float | None = None,
    buffer_mult: float | None = None,
    trend_tier: int | None = None,
) -> float:
    """Permanent hard stop from fill: fill ± (|TV.e−SL| × buffer).

    Missing / tiny TV stop_loss → 0 (caller fail-closes).
    """
    fill = float(entry or 0)
    side_u = str(side or "").upper()
    if fill <= 0 or side_u not in ("LONG", "SHORT"):
        return 0.0
    meta = compute_hard_stop_distance(
        fill_entry=fill,
        tv_stop_loss=tv_stop_loss,
        tv_entry=tv_entry,
        initial_atr=initial_atr,
        symbol=symbol,
        slip_mult=slip_mult,
        buffer_mult=buffer_mult,
        trend_tier=trend_tier,
    )
    dist = float(meta.get("final_dist") or 0)
    if dist <= 0:
        return 0.0
    if side_u == "LONG":
        return fill - dist
    return fill + dist


def hard_stop_meta_for_logs(
    *,
    fill_entry: float,
    tv_stop_loss: float,
    tv_entry: float | None = None,
    symbol: str | None = None,
) -> dict[str, float | str]:
    meta = compute_hard_stop_distance(
        fill_entry=fill_entry,
        tv_stop_loss=tv_stop_loss,
        tv_entry=tv_entry,
        symbol=symbol,
    )
    return {
        "tv_stop_loss": float(tv_stop_loss or 0),
        "tv_stop_distance": float(meta.get("tv_stop_distance") or 0),
        "actual_stop_distance": float(meta.get("final_dist") or 0),
        "buffer_mult": float(meta.get("buffer_mult") or TEMP_TV_STOP_BUFFER),
        "reject_reason": str(meta.get("reject_reason") or ""),
    }


def tv_raw_stop_distance(
    *,
    tv_stop_loss: float,
    tv_entry: float | None = None,
    fill_entry: float | None = None,
    initial_atr: float | None = None,
) -> float:
    """TV original stop distance (no 1.2 buffer)."""
    tv_sl = float(tv_stop_loss or 0)
    tv_e = float(tv_entry or 0) or float(fill_entry or 0)
    if tv_sl > 0 and tv_e > 0:
        return abs(tv_e - tv_sl)
    atr = float(initial_atr or 0)
    return atr if atr > 0 else 0.0


def favorable_move(side: str | None, entry: float, price: float) -> float:
    side_u = str(side or "").upper()
    e = float(entry or 0)
    px = float(price or 0)
    if e <= 0 or px <= 0:
        return 0.0
    if side_u == "LONG":
        return max(0.0, px - e)
    if side_u == "SHORT":
        return max(0.0, e - px)
    return 0.0


def apply_stop_order_buffer(
    side: str | None,
    stop: float,
    symbol: str | None = None,
) -> float:
    """Exchange hang price: LONG −buffer / SHORT +buffer."""
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


def _tier_overrides(legacy: dict[str, Any], profile) -> dict[str, float | None]:
    """Pull tier / reentry overrides from kwargs (None = use profile)."""
    _ = profile

    def _f(key: str) -> float | None:
        if key not in legacy or legacy.get(key) is None:
            return None
        try:
            v = float(legacy[key])
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None

    tp1_d = _f("tp1_dist")
    if tp1_d is None:
        tp1_d = _f("radar_tp1_distance")

    return {
        "step_trigger_atr": _f("step_trigger_atr"),
        "step_advance_atr": _f("step_advance_atr"),
        "coef_min": _f("coef_min"),
        "coef_max": _f("coef_max"),
        "breath_tp1_tp2_atr": _f("breath_tp1_tp2_atr"),
        "breath_tp2_tp3_atr": _f("breath_tp2_tp3_atr"),
        "tp1_price": _f("tp1_price"),
        "tp2_price": _f("tp2_price"),
        "tp3_price": _f("tp3_price"),
        "tv_entry": _f("tv_entry"),
        "tp1_dist": tp1_d,
        "radar_activated": legacy.get("radar_activated"),
        "is_reentry": legacy.get("is_reentry"),
        "reentry_attempt": legacy.get("reentry_attempt"),
    }


def _resolve_tp_prices(
    entry: float,
    atr: float,
    side: str,
    symbol: str | None,
    ov: dict[str, float | None],
) -> tuple[float, float, float]:
    """Resolve TP absolute prices from overrides or ATR-distance fallback."""
    p = profile_for_symbol(symbol)
    sign = 1.0 if str(side).upper() == "LONG" else -1.0
    t1 = float(ov.get("tp1_price") or 0) or (entry + sign * p.tp1_atr * atr)
    t2 = float(ov.get("tp2_price") or 0) or (entry + sign * 2.5 * atr)
    t3 = float(ov.get("tp3_price") or 0) or (entry + sign * 4.0 * atr)
    return t1, t2, t3


def _breath_zone_atr(
    price: float,
    tp1: float,
    tp2: float,
    tp3: float,
    side: str,
    coef: float,
    tier_params,
) -> tuple[float, str]:
    """Determine breath zone and return (breath_atr, zone_label)."""
    side_u = str(side).upper()
    if side_u == "LONG":
        if price >= tp3:
            return coef, "tp3_trail"
        if price >= tp2:
            return float(tier_params.breath_tp2_tp3_atr), "tp2_tp3"
        return float(tier_params.breath_tp1_tp2_atr), "tp1_tp2"
    else:
        if price <= tp3:
            return coef, "tp3_trail"
        if price <= tp2:
            return float(tier_params.breath_tp2_tp3_atr), "tp2_tp3"
        return float(tier_params.breath_tp1_tp2_atr), "tp1_tp2"


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
    smooth_ratio: float | None = None,
    tier: int = 1,
    **_legacy: Any,
) -> tuple[float, float, bool, dict[str, Any]]:
    """Spec §6.0/§6.1: early breakeven checkpoint + absolute price anchor radar arm.

    Phase 0 (early breakeven): price reaches entry + tp1_distance × 0.5 → move SL to BE.
    Phase 1 (radar arm): price reaches (TP1 + TP2) / 2 → activate radar.
    """
    from app.core.radar_trail import fee_cover_breakeven_stop
    from app.core.trend_tier_params import (
        RADAR_ARM_MODE_ABSOLUTE,
        is_reentry_attempt,
        early_breakeven_trigger_price,
        early_breakeven_reached,
        radar_arm_absolute_trigger,
        radar_armed_by_absolute_price,
        params_for_tier,
    )

    p = profile_for_symbol(symbol)
    ov = _tier_overrides(_legacy, p)
    tier_params = params_for_tier(int(tier), symbol)

    step_adv_atr = float(ov["step_advance_atr"] if ov["step_advance_atr"] is not None else tier_params.step_advance_atr)
    step_trig = float(ov["step_trigger_atr"] if ov["step_trigger_atr"] is not None else tier_params.step_trigger_atr)
    try:
        re_att = int(ov.get("reentry_attempt") or 0)
    except (TypeError, ValueError):
        re_att = 0
    reentry = is_reentry_attempt(re_att, is_reentry=ov.get("is_reentry"))

    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = resolve_atr(initial_atr)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    highest_price = float(highest_price or entry_price or 0)
    coef = resolve_coef(breathing_coefficient, p)
    tp1, tp2, tp3 = _resolve_tp_prices(entry_price, initial_atr, "LONG", symbol, ov)

    new_highest = max(highest_price, price) if price > 0 else highest_price
    new_stop = current_stop if current_stop > 0 else initial_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {
        "mode": "phase2" if new_phase else "phase1",
        "breathing_coefficient": coef,
        "symbol_tag": p.symbol_tag,
        "step_trigger_atr": step_trig,
        "step_advance_atr": step_adv_atr,
        "activate_mode": "fee_cover_be",
        "coef_min": float(tier_params.trail_coef_min),
        "coef_max": float(tier_params.trail_coef_max),
        "is_reentry": reentry,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "early_breakeven_trigger": 0.0,
        "early_breakeven_armed": False,
        "radar_arm_trigger": 0.0,
        "radar_armed": False,
        "radar_arm_mode": RADAR_ARM_MODE_ABSOLUTE,
    }

    # === Phase 0: Early breakeven checkpoint (Spec §6.0) ===
    early_trig = early_breakeven_trigger_price(entry_price, tp1, "LONG")
    early_armed = early_breakeven_reached(price, entry_price, tp1, "LONG")
    meta["early_breakeven_trigger"] = early_trig
    meta["early_breakeven_armed"] = early_armed

    if early_armed and not reentry:
        eb_stop = fee_cover_breakeven_stop(entry_price, "LONG", symbol)
        if eb_stop > new_stop + 1e-12 or new_stop <= 0:
            new_stop = eb_stop
            if event == "none":
                event = "early_breakeven"
            meta["event"] = event
            meta["step_count"] = 0
            meta["early_breakeven_atr"] = 0.5
            return new_stop, new_highest, new_phase, meta

    # === Phase 1: Radar arm check (Spec §6.1 — absolute price anchor) ===
    arm_trig = radar_arm_absolute_trigger(tp1, tp2, is_reentry=reentry)
    armed = bool(ov.get("radar_activated")) or radar_armed_by_absolute_price(
        side="LONG",
        price=price,
        tp1=tp1,
        tp2=tp2,
        is_reentry=reentry,
    )
    meta["radar_arm_trigger"] = arm_trig
    meta["radar_armed"] = armed

    if not armed:
        meta["event"] = "waiting_radar_arm"
        meta["step_count"] = 0
        return new_stop, new_highest, new_phase, meta

    # Radar activated: lift to fee+tick breakeven
    activate_stop = fee_cover_breakeven_stop(entry_price, "LONG", symbol)
    meta["activate_stop"] = activate_stop
    trail_dist = initial_atr * coef
    step_size = step_trig * initial_atr if step_trig > 0 else 0.0

    if not bool(ov.get("radar_activated")):
        candidate = max(new_stop, activate_stop) if new_stop > 0 else activate_stop
        if candidate > current_stop + 1e-12 or current_stop <= 0:
            event = "radar_activate"
        new_stop = candidate
        meta["event"] = event
        meta["step_count"] = 0
        meta["just_activated"] = True

    # Breath zone + trail
    breath_atr, zone = _breath_zone_atr(
        price, tp1, tp2, tp3, "LONG", coef, tier_params,
    )
    meta["breath_zone"] = zone
    meta["breath_atr"] = breath_atr
    trail_stop = new_highest - breath_atr * initial_atr

    if new_phase:
        trailed = new_highest - trail_dist
        candidate = max(new_stop, activate_stop, trailed)
        if event == "none":
            event = "phase2_enter" if not breakeven_phase else "trail"
        meta["mode"] = "phase2"
        meta["trail_dist_atr"] = coef
        meta["trail_distance"] = trail_dist
    else:
        step_stop = new_highest - step_size if step_size > 0 else new_highest
        candidate = max(new_stop, activate_stop, step_stop, trail_stop)
        if candidate > new_stop + 1e-12 and event == "none":
            event = "step" if step_size > 0 else "trail"

    new_stop = candidate
    meta["event"] = event
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
    smooth_ratio: float | None = None,
    tier: int = 1,
    **_legacy: Any,
) -> tuple[float, float, bool, dict[str, Any]]:
    """Spec §6.0/§6.1: early breakeven checkpoint + absolute price anchor radar arm."""
    from app.core.radar_trail import fee_cover_breakeven_stop
    from app.core.trend_tier_params import (
        RADAR_ARM_MODE_ABSOLUTE,
        is_reentry_attempt,
        early_breakeven_trigger_price,
        early_breakeven_reached,
        radar_arm_absolute_trigger,
        radar_armed_by_absolute_price,
        params_for_tier,
    )

    p = profile_for_symbol(symbol)
    ov = _tier_overrides(_legacy, p)
    tier_params = params_for_tier(int(tier), symbol)

    step_adv_atr = float(ov["step_advance_atr"] if ov["step_advance_atr"] is not None else tier_params.step_advance_atr)
    step_trig = float(ov["step_trigger_atr"] if ov["step_trigger_atr"] is not None else tier_params.step_trigger_atr)
    try:
        re_att = int(ov.get("reentry_attempt") or 0)
    except (TypeError, ValueError):
        re_att = 0
    reentry = is_reentry_attempt(re_att, is_reentry=ov.get("is_reentry"))

    price = float(price or 0)
    entry_price = float(entry_price or 0)
    initial_atr = resolve_atr(initial_atr)
    initial_stop = float(initial_stop or 0)
    current_stop = float(current_stop or 0)
    lowest_price = float(lowest_price or entry_price or 0)
    coef = resolve_coef(breathing_coefficient, p)
    tp1, tp2, tp3 = _resolve_tp_prices(entry_price, initial_atr, "SHORT", symbol, ov)

    new_lowest = min(lowest_price, price) if price > 0 else lowest_price
    if lowest_price <= 0 and price > 0:
        new_lowest = price
    new_stop = current_stop if current_stop > 0 else initial_stop
    new_phase = bool(breakeven_phase)
    event = "none"
    meta: dict[str, Any] = {
        "mode": "phase2" if new_phase else "phase1",
        "breathing_coefficient": coef,
        "symbol_tag": p.symbol_tag,
        "step_trigger_atr": step_trig,
        "step_advance_atr": step_adv_atr,
        "activate_mode": "fee_cover_be",
        "coef_min": float(tier_params.trail_coef_min),
        "coef_max": float(tier_params.trail_coef_max),
        "is_reentry": reentry,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "early_breakeven_trigger": 0.0,
        "early_breakeven_armed": False,
        "radar_arm_trigger": 0.0,
        "radar_armed": False,
        "radar_arm_mode": RADAR_ARM_MODE_ABSOLUTE,
    }

    # === Phase 0: Early breakeven checkpoint (Spec §6.0) ===
    early_trig = early_breakeven_trigger_price(entry_price, tp1, "SHORT")
    early_armed = early_breakeven_reached(price, entry_price, tp1, "SHORT")
    meta["early_breakeven_trigger"] = early_trig
    meta["early_breakeven_armed"] = early_armed

    if early_armed and not reentry:
        eb_stop = fee_cover_breakeven_stop(entry_price, "SHORT", symbol)
        if eb_stop < new_stop - 1e-12 or new_stop <= 0:
            new_stop = eb_stop
            if event == "none":
                event = "early_breakeven"
            meta["event"] = event
            meta["step_count"] = 0
            meta["early_breakeven_atr"] = 0.5
            return new_stop, new_lowest, new_phase, meta

    # === Phase 1: Radar arm check (Spec §6.1 — absolute price anchor) ===
    arm_trig = radar_arm_absolute_trigger(tp1, tp2, is_reentry=reentry)
    armed = bool(ov.get("radar_activated")) or radar_armed_by_absolute_price(
        side="SHORT",
        price=price,
        tp1=tp1,
        tp2=tp2,
        is_reentry=reentry,
    )
    meta["radar_arm_trigger"] = arm_trig
    meta["radar_armed"] = armed

    if not armed:
        meta["event"] = "waiting_radar_arm"
        meta["step_count"] = 0
        return new_stop, new_lowest, new_phase, meta

    activate_stop = fee_cover_breakeven_stop(entry_price, "SHORT", symbol)
    meta["activate_stop"] = activate_stop
    trail_dist = initial_atr * coef
    step_size = step_trig * initial_atr if step_trig > 0 else 0.0

    if not bool(ov.get("radar_activated")):
        if current_stop <= 0:
            candidate = activate_stop
        else:
            candidate = min(current_stop, activate_stop)
        if current_stop <= 0 or candidate < current_stop - 1e-12:
            event = "radar_activate"
        new_stop = candidate
        meta["event"] = event
        meta["step_count"] = 0
        meta["just_activated"] = True

    # Breath zone + trail
    breath_atr, zone = _breath_zone_atr(
        price, tp1, tp2, tp3, "SHORT", coef, tier_params,
    )
    meta["breath_zone"] = zone
    meta["breath_atr"] = breath_atr
    trail_stop = new_lowest + breath_atr * initial_atr

    if new_phase:
        trailed = new_lowest + trail_dist
        candidate = min(new_stop, activate_stop, trailed)
        if event == "none":
            event = "phase2_enter" if not breakeven_phase else "trail"
        meta["mode"] = "phase2"
        meta["trail_dist_atr"] = coef
        meta["trail_distance"] = trail_dist
    else:
        step_stop = new_lowest + step_size if step_size > 0 else new_lowest
        candidate = min(new_stop, activate_stop, step_stop, trail_stop)
        if candidate < new_stop - 1e-12 and event == "none":
            event = "step" if step_size > 0 else "trail"

    new_stop = candidate
    meta["event"] = event
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
    symbol: str | None = None,
    smooth_ratio: float | None = None,
    tier: int = 1,
    step_trigger_atr: float | None = None,
    step_advance_atr: float | None = None,
    coef_min: float | None = None,
    coef_max: float | None = None,
    breath_tp1_tp2_atr: float | None = None,
    breath_tp2_tp3_atr: float | None = None,
    tp1_price: float | None = None,
    tp2_price: float | None = None,
    tp3_price: float | None = None,
    radar_activated: bool | None = None,
    tv_entry: float | None = None,
    tp1_dist: float | None = None,
    radar_tp1_distance: float | None = None,
    is_reentry: bool | None = None,
    reentry_attempt: int | None = None,
    **_legacy_kw: Any,
) -> dict[str, Any]:
    p = profile_for_symbol(symbol)
    sr = float(smooth_ratio if smooth_ratio is not None else COLD_START_RATIO)
    coef = resolve_coef(breathing_coefficient, p)
    side_u = str(side or "").upper()
    dist = tp1_dist if tp1_dist is not None else radar_tp1_distance
    tier_kw = {
        "step_trigger_atr": step_trigger_atr,
        "step_advance_atr": step_advance_atr,
        "coef_min": coef_min,
        "coef_max": coef_max,
        "breath_tp1_tp2_atr": breath_tp1_tp2_atr,
        "breath_tp2_tp3_atr": breath_tp2_tp3_atr,
        "tp1_price": tp1_price,
        "tp2_price": tp2_price,
        "tp3_price": tp3_price,
        "radar_activated": radar_activated,
        "tv_entry": tv_entry,
        "tp1_dist": dist,
        "is_reentry": is_reentry,
        "reentry_attempt": reentry_attempt,
    }
    if side_u == "LONG":
        new_stop, peak, phase, meta = calculate_stop_long(
            price, entry_price, initial_atr, initial_stop,
            current_stop, best_price, breakeven_phase, coef,
            symbol=symbol, smooth_ratio=sr, tier=tier, **tier_kw,
        )
    elif side_u == "SHORT":
        new_stop, peak, phase, meta = calculate_stop_short(
            price, entry_price, initial_atr, initial_stop,
            current_stop, best_price, breakeven_phase, coef,
            symbol=symbol, smooth_ratio=sr, tier=tier, **tier_kw,
        )
    else:
        return {
            "current_sl": float(current_stop or 0),
            "best_price": float(best_price or 0),
            "breakeven_phase": bool(breakeven_phase),
            "event": "none",
            "improved": False,
            "breathing_coefficient": coef,
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
        "breathing_coefficient": coef,
        "step_count": int(meta.get("step_count") or 0),
        "meta": meta,
        "initial_atr": resolve_atr(initial_atr),
        "initial_stop": float(initial_stop or 0),
        "symbol_tag": meta.get("symbol_tag"),
        "radar_armed": bool(meta.get("radar_armed")),
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
    from app.core.trend_tier_params import params_for_tier

    p = profile_for_symbol(symbol)
    mid = params_for_tier(1, symbol)
    return (
        f"[{p.symbol_tag}] 硬止损呼吸垫固定1.15"
        f" · 雷达启动=绝对价格锚定：首次(TP1+TP2)/2，重入TP2"
        f" · 激活→手续费保本(fee+tick)"
        f" · 步进{mid.step_trigger_atr}/{mid.step_advance_atr}×ATR(中档)"
        f" · 追踪{mid.trail_coef_min}~{mid.trail_coef_max}×ATR"
        f" · 重入仅强趋势·最多1次/{mid.reentry_bars}根K"
    )
