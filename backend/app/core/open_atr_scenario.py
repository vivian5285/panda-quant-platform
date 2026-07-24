"""Open-time ATR scenario: VPS native 1h ATR preferred; TV atr fallback for radar.

2026-07-25: TP1/TP2/TP3 limits always hung (10/20/70). ATR scenario only selects
radar ``initial_atr`` source — never cancels TP3, never rewrites hard stop.
Hard stop = |TV.price−TV.stop_loss| × buffer from fill.
"""

from __future__ import annotations

from typing import Any

from app.core.atr_1h_breathing import (
    compute_atr_1h_from_klines,
    _cache_key,
    _fetch_1h_klines,
    _lock,
    _cache,
)
from app.core.breathing_stop import compute_initial_stop, compute_temp_tv_stop
from app.core.initial_atr_lock import rewrite_initial_atr_for_vps_upgrade
from app.core.symbol_registry import normalize_canonical_symbol
from app.core.tp_regime_targets import placeable_tp_levels

ATR_SCENARIO_VPS = "vps_real"
ATR_SCENARIO_TV = "tv_fallback"
ATR_SCENARIO_PENDING = "pending"


def fetch_vps_1h_atr_fresh(*, client: Any = None, symbol: str | None = None) -> tuple[float, bool]:
    """Force-fetch exchange-native 1h ATR. ok=True only when this attempt computes atr>0."""
    import time

    can = normalize_canonical_symbol(symbol) or "ETHUSDT"
    rows = _fetch_1h_klines(client, can)
    atr = compute_atr_1h_from_klines(rows)
    now = time.time()
    key = _cache_key(can)
    with _lock:
        prev = _cache.get(key) or {}
        if atr <= 0:
            return 0.0, False
        _cache[key] = {
            "atr": atr,
            "fetched_at": now,
            "ratios": list(prev.get("ratios") or []),
        }
    return float(atr), True


def resolve_open_atr(
    *,
    client: Any = None,
    symbol: str | None = None,
    tv_atr: float = 0.0,
) -> dict[str, Any]:
    """Decide radar ATR source. TP3 limit always active."""
    atr_1h, ok = fetch_vps_1h_atr_fresh(client=client, symbol=symbol)
    tv = float(tv_atr or 0)
    if ok and atr_1h > 0:
        return {
            "scenario": ATR_SCENARIO_VPS,
            "initial_atr": float(atr_1h),
            "atr_1h": float(atr_1h),
            "tv_atr": tv,
            "tp3_limit_active": True,
            "atr_source": "vps_1h",
        }
    return {
        "scenario": ATR_SCENARIO_TV,
        "initial_atr": tv,
        "atr_1h": float(atr_1h or 0),
        "tv_atr": tv,
        "tp3_limit_active": True,
        "atr_source": "tv_webhook",
    }


def apply_vps_atr_upgrade(
    supervisor: Any,
    atr_1h: float,
    *,
    live_qty: float = 0.0,
) -> dict[str, Any]:
    """Scenario2→1: rewrite radar initial_atr only. Keep TP3. Never touch hard."""
    atr = float(atr_1h or 0)
    if atr <= 0:
        return {"upgraded": False, "reason": "atr_invalid"}
    if not rewrite_initial_atr_for_vps_upgrade(supervisor, atr, reason="vps_1h_upgrade"):
        return {"upgraded": False, "reason": "rewrite_failed"}

    frozen_hard = float(
        getattr(supervisor, "_frozen_hard_stop_px", 0)
        or getattr(supervisor, "_tv_hard_sl_price", 0)
        or 0
    )

    entry = float(getattr(supervisor, "watched_entry", 0) or 0)
    side = str(getattr(supervisor, "current_side", "") or "").upper()
    sym = getattr(supervisor, "canonical_symbol", None) or getattr(supervisor, "symbol", None)
    old_sl = float(getattr(supervisor, "current_sl", 0) or 0)
    new_init = compute_initial_stop(entry, side, atr, symbol=sym) if entry > 0 and side in ("LONG", "SHORT") else 0.0
    if new_init > 0:
        supervisor.initial_stop = new_init
        if old_sl <= 0:
            supervisor.current_sl = new_init
        elif side == "LONG":
            supervisor.current_sl = max(old_sl, new_init)
        elif side == "SHORT":
            supervisor.current_sl = min(old_sl, new_init)
        if hasattr(supervisor, "_clamp_radar_sl_to_tv_floor"):
            try:
                supervisor.current_sl = supervisor._clamp_radar_sl_to_tv_floor(
                    float(supervisor.current_sl)
                )
            except Exception:
                pass

    if frozen_hard > 0:
        supervisor._frozen_hard_stop_px = frozen_hard
        supervisor._tv_hard_sl_price = frozen_hard

    supervisor.current_atr = atr
    supervisor.atr_1h = atr
    supervisor.atr_scenario = ATR_SCENARIO_VPS
    supervisor.tp3_limit_active = True  # never cancel TP3 on ATR upgrade
    supervisor._temp_tv_stop_active = False

    try:
        from app.core.atr_1h_breathing import refresh_supervisor_breath
        refresh_supervisor_breath(supervisor, force=True)
    except Exception:
        pass

    if live_qty > 0 and hasattr(supervisor, "_ensure_radar_sl"):
        radar = float(getattr(supervisor, "current_sl", 0) or 0)
        if radar > 0:
            try:
                if getattr(supervisor, "exchange_id", "") == "deepcoin":
                    supervisor._ensure_radar_sl(live_qty, radar)
                else:
                    hang = radar
                    if hasattr(supervisor, "_exchange_hang_stop_px"):
                        hang = supervisor._exchange_hang_stop_px(radar) or radar
                    supervisor._ensure_radar_sl(hang, live_qty)
            except Exception:
                pass

    detail = {
        "upgraded": True,
        "scenario": ATR_SCENARIO_VPS,
        "initial_atr": atr,
        "initial_stop": float(getattr(supervisor, "initial_stop", 0) or 0),
        "current_sl": float(getattr(supervisor, "current_sl", 0) or 0),
        "frozen_hard": float(getattr(supervisor, "_frozen_hard_stop_px", 0) or 0),
        "tp3_cancelled": 0,
        "tp3_limit_active": True,
    }
    if hasattr(supervisor, "_log"):
        supervisor._log(
            "ATR_SCENARIO",
            "VPS真实ATR已武装雷达（TP3限价保留·硬止损永冻）",
            detail,
        )
    if hasattr(supervisor, "_alert"):
        supervisor._alert(
            "info",
            "ATR_SCENARIO",
            "VPS真实ATR恢复·已切回场景一",
            "雷达已用交易所1h ATR；TP1/2/3限价不撤",
            detail,
        )
    return detail


def maybe_retry_vps_atr_on_tick(supervisor: Any, live_qty: float = 0.0) -> dict[str, Any]:
    """Breath-tick hook: if still on TV fallback, retry VPS 1h ATR upgrade (keep TP3)."""
    if str(getattr(supervisor, "atr_scenario", "") or "") != ATR_SCENARIO_TV:
        return {"attempted": False}
    client = getattr(supervisor, "client", None)
    sym = (
        getattr(supervisor, "canonical_symbol", None)
        or getattr(supervisor, "symbol", None)
        or "ETHUSDT"
    )
    atr, ok = fetch_vps_1h_atr_fresh(client=client, symbol=sym)
    if not ok:
        return {"attempted": True, "upgraded": False, "atr_1h": 0.0}
    return apply_vps_atr_upgrade(supervisor, atr, live_qty=live_qty)


def supervisor_placeable_levels(supervisor: Any) -> frozenset[int]:
    """Always TP1+TP2+TP3."""
    return placeable_tp_levels(tp3_limit_active=True)


def enrich_open_atr_detail(detail: dict | None = None, **extra: Any) -> dict[str, Any]:
    out = dict(detail or {})
    out.update(extra)
    return out


__all__ = [
    "ATR_SCENARIO_PENDING",
    "ATR_SCENARIO_TV",
    "ATR_SCENARIO_VPS",
    "apply_vps_atr_upgrade",
    "compute_temp_tv_stop",
    "fetch_vps_1h_atr_fresh",
    "maybe_retry_vps_atr_on_tick",
    "resolve_open_atr",
    "supervisor_placeable_levels",
    "enrich_open_atr_detail",
]
