"""Breathing stop orchestration — merged hard SL + radar (all exchanges)."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.core.atr_1h_breathing import refresh_supervisor_breath
from app.core.breathing_profile import cold_start_multiplier, profile_for_symbol
from app.core.breathing_stop import (
    INITIAL_SL_ATR,
    apply_breathing_tick,
    apply_stop_order_buffer,
    compute_initial_stop,
    compute_temp_tv_stop,
    init_breathing_state,
    resolve_adx,
    resolve_atr,
    resolve_breathing_coef,
    stop_hit,
)
from app.core.initial_atr_lock import InitialAtrDescriptor
from app.core.open_atr_scenario import (
    ATR_SCENARIO_PENDING,
    ATR_SCENARIO_TV,
    ATR_SCENARIO_VPS,
    maybe_retry_vps_atr_on_tick,
    resolve_open_atr,
)
from app.core.market_engine import (
    atr_mismatch_ratio,
    ensure_fresh,
    force_refresh,
    implied_atr_from_tv_stop,
)
from app.core.position_qty_tolerance import qty_drift_tolerance
from app.core.radar_trail import (
    clamp_stop_market_safe,
    stop_would_trigger_immediately,
    tp1_distance,
    tp_path_progress,
)
from app.core.vps_hard_sl import compute_hard_sl_limit_price
from app.core.vps_radar_stages import tp1_filled_from_consumed
from app.core.symbol_precision import round_price, round_quantity

logger = logging.getLogger(__name__)

# TV hard stop from webhook tv_sl; legacy 10% kept only for fill-attribution helpers.
ADVERSE_HARD_STOP_PCT = 0.10
TV_SL_TIER_MARKER = -1.0  # plan tier_pct when stop price comes from TV
ADVERSE_STOP_TOLERANCE = 2.0
ADVERSE_REPAIR_COOLDOWN_SEC = 20.0
ADVERSE_MAX_STOP_ORDERS = 2  # hard + radar coexistence (whitepaper)
ADVERSE_VERIFY_RETRIES = 6
ADVERSE_VERIFY_RETRY_DELAY_SEC = 0.5
# Legacy aliases (tests / imports)
ADVERSE_ARM_PCT = ADVERSE_HARD_STOP_PCT
ADVERSE_SL_TIERS = (ADVERSE_HARD_STOP_PCT,)
ADVERSE_MAX_TIER_ORDERS = ADVERSE_MAX_STOP_ORDERS


def parse_tv_sl(raw) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        px = round_price(float(raw))
        return px if px > 0 else None
    except (TypeError, ValueError):
        return None


def adverse_hard_stop_price(entry: float, side: str) -> float:
    """Entry-anchored 10% hard stop trigger price."""
    if entry <= 0 or side not in ("LONG", "SHORT"):
        return 0.0
    if side == "LONG":
        return round_price(entry * (1.0 - ADVERSE_HARD_STOP_PCT))
    return round_price(entry * (1.0 + ADVERSE_HARD_STOP_PCT))


def adverse_tier_stop_prices(entry: float, side: str) -> set[float]:
    """Shield stop price set (single 10% tier)."""
    px = adverse_hard_stop_price(entry, side)
    return {px} if px > 0 else set()


def adverse_shield_stop_prices(entry: float, side: str) -> set[float]:
    return adverse_tier_stop_prices(entry, side)


def _order_stop_price(o: dict) -> float:
    for key in ("stopPrice", "triggerPrice", "activatePrice"):
        val = o.get(key)
        if val is not None and str(val).strip() not in ("", "0"):
            try:
                px = round(float(val), 2)
                if px > 0:
                    return px
            except (TypeError, ValueError):
                continue
    return 0.0


def _order_limit_price(o: dict) -> float:
    try:
        px = float(o.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(px, 2) if px > 0 else 0.0


def _adverse_defense_price(o: dict) -> float:
    """Stop trigger, or resting reduce-only LIMIT price used as hard SL."""
    px = _order_stop_price(o)
    if px > 0:
        return px
    if str(o.get("type") or o.get("orderType") or "").upper() == "LIMIT":
        return _order_limit_price(o)
    return 0.0


def _order_is_reduce_only(o: dict) -> bool:
    val = o.get("reduceOnly")
    if val is True:
        return True
    if isinstance(val, str) and val.strip().lower() in ("true", "1"):
        return True
    return False


def _order_qty_value(o: dict) -> float:
    for key in ("origQty", "quantity", "sz", "size"):
        val = o.get(key)
        if val is not None and str(val).strip() not in ("", "0"):
            try:
                q = abs(float(val))
                if q > 0:
                    return q
            except (TypeError, ValueError):
                continue
    return 0.0


def _order_is_close_position(o: dict) -> bool:
    val = o.get("closePosition")
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1")
    return bool(val)


def _is_stop_market_like(o: dict) -> bool:
    """Recognize STOP / STOP_MARKET on regular book and Binance algo conditional book."""
    otype = str(o.get("type") or o.get("orderType") or "").upper()
    if otype in ("STOP_MARKET", "STOP", "TAKE_PROFIT", "TAKE_PROFIT_MARKET"):
        return True
    if o.get("isAlgoOrder") and _order_stop_price(o) > 0:
        # Algo CONDITIONAL with trigger — covers STOP and STOP_MARKET
        if otype in ("", "CONDITIONAL") or "STOP" in otype or otype.endswith("_MARKET"):
            return True
    return False


def order_qty_covers_tier(o: dict, target_qty: float, qty_tol: float) -> bool:
    """Full-position stop: closePosition or STOP_MARKET without origQty still counts."""
    if _order_is_close_position(o):
        return True
    live_q = _order_qty_value(o)
    if live_q <= 0 and str(o.get("type", "")).upper() in ("STOP_MARKET", "STOP"):
        return True
    return abs(live_q - target_qty) <= qty_tol


def adverse_move_pct(entry: float, price: float, side: str | None) -> float:
    """Positive fraction when price moved against the position (0 = flat or favorable)."""
    if entry <= 0 or price <= 0 or side not in ("LONG", "SHORT"):
        return 0.0
    if side == "LONG":
        return max(0.0, (entry - price) / entry)
    return max(0.0, (price - entry) / entry)


def is_floating_profit(entry: float, price: float, side: str | None) -> bool:
    """True when mark price is on the profitable side of entry."""
    if entry <= 0 or price <= 0 or side not in ("LONG", "SHORT"):
        return False
    if side == "LONG":
        return price > entry
    return price < entry


def favorable_move_pct(entry: float, price: float, side: str | None) -> float:
    if entry <= 0 or price <= 0 or side not in ("LONG", "SHORT"):
        return 0.0
    if side == "LONG":
        return max(0.0, (price - entry) / entry)
    return max(0.0, (entry - price) / entry)


def compute_adverse_stop_plan(
    entry: float,
    side: str,
    live_qty: float,
    *,
    round_qty_fn,
    consumed_tiers: set[float] | None = None,
    tv_sl_price: float | None = None,
) -> list[dict[str, Any]]:
    """Full-position hard stop — TV tv_sl only (no legacy 10% fallback)."""
    if live_qty <= 0:
        return []
    qty = round_qty_fn(live_qty)
    if qty <= 0:
        return []

    tv_px = parse_tv_sl(tv_sl_price)
    if not tv_px:
        return []

    return [{
        "tier_pct": TV_SL_TIER_MARKER,
        "stop_price": tv_px,
        "qty": qty,
        "level": 1,
        "source": "tv_hard_sl",
    }]


def match_adverse_tier_fill(
    entry: float,
    side: str,
    old_qty: float,
    reduced_qty: float,
    *,
    round_qty_fn,
    qty_tol: float | None = None,
    tv_sl_price: float | None = None,
) -> float | None:
    """If reduction matches full-position TV hard stop, return tier marker."""
    if old_qty <= 0 or reduced_qty <= 0:
        return None
    tol = qty_tol if qty_tol is not None else qty_drift_tolerance(old_qty, old_qty)
    plan = compute_adverse_stop_plan(
        entry, side, old_qty, round_qty_fn=round_qty_fn, tv_sl_price=tv_sl_price,
    )
    if not plan:
        return None
    tier = plan[0]
    if abs(reduced_qty - float(tier["qty"])) <= tol:
        return float(tier["tier_pct"])
    return None


class AdverseRadarMixin:
    """
    Dual-track defense (all exchanges / ETH+XAU) — whitepaper coexistence:
    - Hard stop: TV stop_loss×1.2 at open, price frozen until flat (qty may shrink)
    - Radar stop: independent ATR breathing (scenario1=VPS 1h, scenario2=TV atr)
    - TP1/TP2 always; TP3 only scenario2
    """

    # initial_atr locked after open; flat→0 clears; VPS upgrade may rewrite
    initial_atr = InitialAtrDescriptor()

    adverse_sl_armed: bool
    adverse_sl_prices: list[float]
    adverse_consumed_tiers: list[float]

    def _symbol_tag(self) -> str:
        from app.core.breathing_profile import symbol_tag
        can = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        return f"[{symbol_tag(can)}]"

    def _init_adverse_radar_fields(self) -> None:
        if not hasattr(self, "tv_sl"):
            self.tv_sl = 0.0
        if not hasattr(self, "_tv_stop_loss_ref"):
            self._tv_stop_loss_ref = 0.0
        if not hasattr(self, "adverse_sl_armed"):
            self.adverse_sl_armed = False
        if not hasattr(self, "adverse_sl_prices"):
            self.adverse_sl_prices = []
        if not hasattr(self, "adverse_consumed_tiers"):
            self.adverse_consumed_tiers = []
        if not hasattr(self, "_adverse_last_repair_ts"):
            self._adverse_last_repair_ts = 0.0
        if not hasattr(self, "adverse_arm_dingtalk_sent"):
            self.adverse_arm_dingtalk_sent = False
        if not hasattr(self, "_pending_adverse_algo_ids"):
            self._pending_adverse_algo_ids = []
        if not hasattr(self, "radar_latched"):
            self.radar_latched = False
        if not hasattr(self, "radar_activated"):
            self.radar_activated = False
        if not hasattr(self, "radar_step_count"):
            self.radar_step_count = 0
        if not hasattr(self, "_atr_refreshed_at"):
            self._atr_refreshed_at = 0.0
        if not hasattr(self, "_tp_placed_at"):
            self._tp_placed_at = {}
        if not hasattr(self, "_defense_order_ids"):
            # Checklist §四/§十一: TP1/TP2/SL tracked by order id (persisted)
            # keys: "1" | "2" | "sl" → exchange orderId/algoId
            self._defense_order_ids = {}
        if not hasattr(self, "_radar_arm_dingtalk_sent"):
            self._radar_arm_dingtalk_sent = False
        if not hasattr(self, "trading_paused"):
            self.trading_paused = False
        if not hasattr(self, "trading_pause_reason"):
            self.trading_pause_reason = ""
        if not hasattr(self, "_radar_path_ok_streak"):
            self._radar_path_ok_streak = 0
        if not hasattr(self, "_last_radar_arm_meta"):
            self._last_radar_arm_meta = {}
        if not hasattr(self, "_tv_hard_sl_price"):
            self._tv_hard_sl_price = 0.0
        if not hasattr(self, "_frozen_hard_stop_px"):
            self._frozen_hard_stop_px = 0.0
        if not hasattr(self, "_vps_hard_sl_meta"):
            self._vps_hard_sl_meta = {}
        if not hasattr(self, "_initial_atr_value"):
            self._initial_atr_value = 0.0
            self._initial_atr_locked = False
        if not hasattr(self, "initial_stop"):
            self.initial_stop = 0.0
        if not hasattr(self, "breakeven_phase"):
            self.breakeven_phase = False
        if not hasattr(self, "breathing_coefficient"):
            can = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
            self.breathing_coefficient = cold_start_multiplier(profile_for_symbol(can))
        if not hasattr(self, "breath_ratio_history"):
            self.breath_ratio_history = []
        if not hasattr(self, "atr_1h"):
            self.atr_1h = 0.0
        if not hasattr(self, "breath_smooth_ratio"):
            self.breath_smooth_ratio = 1.0
        if not hasattr(self, "_tv_atr_ref"):
            self._tv_atr_ref = 0.0
        if not hasattr(self, "current_adx"):
            self.current_adx = resolve_adx(None)
        if not hasattr(self, "remaining_qty_pct"):
            self.remaining_qty_pct = 1.0
        if not hasattr(self, "_last_breath_trail_alert_sl"):
            self._last_breath_trail_alert_sl = 0.0
        if not hasattr(self, "atr_scenario"):
            self.atr_scenario = ATR_SCENARIO_PENDING
        if not hasattr(self, "tp3_limit_active"):
            self.tp3_limit_active = False
        if not hasattr(self, "_temp_tv_stop_active"):
            self._temp_tv_stop_active = False

    def _exchange_stop_px(self) -> float:
        """Logical radar / breathing stop (hard floor is `_frozen_hard_stop_px`)."""
        return float(
            getattr(self, "current_sl", 0)
            or getattr(self, "initial_stop", 0)
            or 0
        )

    def _frozen_hard_px(self) -> float:
        """Permanent hard-stop trigger (TV stop_loss × 1.2). Never rewritten by ATR."""
        return float(
            getattr(self, "_frozen_hard_stop_px", 0)
            or getattr(self, "_tv_hard_sl_price", 0)
            or 0
        )

    def _exchange_hang_stop_px(self, logical_sl: float | None = None) -> float:
        """Exchange order price = logical stop ± 0.3 USDT execution buffer."""
        side = getattr(self, "current_side", None)
        logical = float(logical_sl if logical_sl is not None else self._exchange_stop_px() or 0)
        if logical <= 0:
            return 0.0
        return round_price(
            apply_stop_order_buffer(side, logical, getattr(self, "canonical_symbol", None)),
            getattr(self, "canonical_symbol", None),
        )

    def _pine_stop_loss_ref(self) -> float:
        """TradingView stop_loss only (sizing adjust_coef + ATR compare)."""
        return float(
            getattr(self, "_tv_stop_loss_ref", 0)
            or getattr(self, "_pending_open_tv_sl", 0)
            or 0
        )

    def _pull_vps_market_indicators(self, *, force: bool = False) -> dict[str, Any]:
        """Refresh ATR/ADX from VPS market engine. Never uses TV webhook values.

        On force (open): writes current_atr + current_adx.
        On soft refresh (tick): only updates current_adx; never mutates initial_atr.
        """
        self._init_adverse_radar_fields()
        client = getattr(self, "client", None)
        ex = getattr(self, "exchange_id", None) or getattr(client, "exchange_id", None)
        sym = (
            getattr(self, "canonical_symbol", None)
            or getattr(client, "canonical_symbol", None)
            or getattr(self, "symbol", None)
            or getattr(client, "trading_symbol", None)
        )
        snap = (
            force_refresh(client=client, exchange=ex, symbol=sym)
            if force
            else ensure_fresh(client=client, exchange=ex, symbol=sym)
        )
        atr = float(snap.get("atr") or 0)
        adx = float(snap.get("adx") or 0)
        if atr > 0:
            # Never overwrite frozen initial_atr after open
            live = (
                float(getattr(self, "initial_atr", 0) or 0) > 0
                and (
                    bool(getattr(self, "monitoring", False))
                    or float(getattr(self, "watched_qty", 0) or 0) > 0
                )
            )
            if force or not live:
                self.current_atr = atr
            elif float(getattr(self, "current_atr", 0) or 0) <= 0:
                self.current_atr = atr
        if adx > 0:
            self.current_adx = resolve_adx(adx)
        return snap

    def _maybe_alert_atr_mismatch(
        self,
        entry: float,
        tv_stop: float | None,
        vps_atr: float,
    ) -> None:
        """Debug-only: compare TV stop_loss-implied ATR vs VPS ATR. Never affects stops.

        TV ``stop_loss`` is typically ``entry ± TV_STOP_ATR_MULT×ATR`` (≈1.0), NOT the
        VPS hang price ``entry ± 1.5×ATR``. Using INITIAL_SL_ATR=1.5 here falsely yields
        ~33% mismatch whenever the two ATRs actually agree.
        """
        from app.config import get_settings

        settings = get_settings()
        tv_mult = float(getattr(settings, "TV_STOP_ATR_MULT", 1.0) or 1.0)
        implied = implied_atr_from_tv_stop(
            float(entry or 0), float(tv_stop or 0), initial_sl_atr=tv_mult,
        )
        vps = float(vps_atr or 0)
        if implied <= 0 or vps <= 0:
            return
        ratio = atr_mismatch_ratio(vps, implied)
        warn_pct = float(getattr(settings, "ATR_COMPARE_WARN_PCT", 0.20) or 0.20)
        if ratio < warn_pct:
            logger.info(
                "[User %s] ATR核对 OK: vps=%.4f tv_implied=%.4f (÷%.2f) ratio=%.1f%%",
                getattr(self, "user_id", "?"),
                vps, implied, tv_mult, ratio * 100,
            )
            return
        detail = {
            "vps_atr": vps,
            "tv_implied_atr": implied,
            "tv_stop_atr_mult": tv_mult,
            "tv_stop_loss": float(tv_stop or 0),
            "entry": float(entry or 0),
            "mismatch_pct": round(ratio * 100, 2),
            "warn_pct": warn_pct * 100,
            "note": "仅告警·不参与止损决策；TV隐含=|price−stop|/TV_STOP_ATR_MULT",
        }
        logger.warning(
            "[User %s] ATR核对偏差过大: vps=%.4f tv_implied=%.4f (÷%.2f) Δ=%.1f%%",
            getattr(self, "user_id", "?"),
            vps, implied, tv_mult, ratio * 100,
        )
        if hasattr(self, "_alert"):
            try:
                self._alert(
                    "warning",
                    "ATR_MISMATCH",
                    "ATR双边核对偏差",
                    f"VPS ATR={vps:.4f} vs TV隐含={implied:.4f} "
                    f"(stop÷{tv_mult:g}·Δ{ratio*100:.0f}%) · 请核对90m周期",
                    detail,
                )
            except Exception:
                pass

    def _pause_trading(self, reason: str, detail: dict | None = None) -> None:
        """Checklist §七: missing persist / direction mismatch → alert + pause opens."""
        self._init_adverse_radar_fields()
        self.trading_paused = True
        self.trading_pause_reason = str(reason or "paused")
        if hasattr(self, "_save_state"):
            try:
                self._save_state()
            except Exception:
                pass
        if hasattr(self, "_alert"):
            try:
                self._alert(
                    "critical",
                    "TRADING_PAUSED",
                    "交易已暂停",
                    self.trading_pause_reason,
                    dict(detail or {}),
                )
            except Exception:
                pass

    def _clear_trading_pause(self, reason: str = "") -> None:
        self._init_adverse_radar_fields()
        was = bool(self.trading_paused)
        self.trading_paused = False
        self.trading_pause_reason = ""
        if was and hasattr(self, "_log"):
            try:
                self._log("RESUME", f"交易暂停已解除 {reason}", {"reason": reason})
            except Exception:
                pass

    def _block_if_trading_paused(self, action: str) -> dict | None:
        """Block OPEN when paused; allow force-flat exits and reconcile closes."""
        self._init_adverse_radar_fields()
        if not self.trading_paused:
            return None
        act = str(action or "").upper()
        from app.services.webhook_guard import is_force_flat_close, is_reconcile_only_close
        if is_force_flat_close(act) or is_reconcile_only_close(act):
            return None
        if act in ("LONG", "SHORT", "UPDATE_TP"):
            reason = self.trading_pause_reason or "trading_paused"
            if hasattr(self, "_log"):
                self._log("SIGNAL", f"⏸️ 交易已暂停，忽略 {act}: {reason}", {"action": act})
            return {
                "status": "skipped",
                "reason": "trading_paused",
                "message": reason,
                "action": act,
            }
        return None

    def _mark_tp_placed(self, level: int, order_id=None) -> None:
        """Stamp TP1/TP2/TP3 hang time for 5-min timeout → cancel + hand to radar."""
        lvl = int(level or 0)
        if lvl not in (1, 2, 3):
            return
        placed = dict(getattr(self, "_tp_placed_at", None) or {})
        if lvl not in placed:
            placed[lvl] = time.time()
            self._tp_placed_at = placed
        if order_id is not None:
            self._remember_defense_order_id(str(lvl), order_id)

    def _remember_defense_order_id(self, key: str, order_id) -> None:
        """Persist defense order id for TP1/TP2/TP3/SL (checklist 4.3 / 11.3)."""
        self._init_adverse_radar_fields()
        k = str(key or "").strip().lower()
        if k.startswith("tp"):
            k = k[2:]
        if k not in ("1", "2", "3", "sl"):
            return
        try:
            oid = int(order_id) if order_id is not None and str(order_id).strip() != "" else None
        except (TypeError, ValueError):
            oid = str(order_id).strip() or None
        if oid is None:
            return
        ids = dict(getattr(self, "_defense_order_ids", None) or {})
        if ids.get(k) == oid:
            return
        ids[k] = oid
        self._defense_order_ids = ids

    def _clear_defense_order_ids(self, *keys) -> None:
        self._init_adverse_radar_fields()
        ids = dict(getattr(self, "_defense_order_ids", None) or {})
        if not keys:
            ids.clear()
        else:
            for raw in keys:
                k = str(raw or "").strip().lower()
                if k.startswith("tp"):
                    k = k[2:]
                ids.pop(k, None)
        self._defense_order_ids = ids

    def _defense_order_id(self, key: str):
        ids = getattr(self, "_defense_order_ids", None) or {}
        k = str(key or "").strip().lower()
        if k.startswith("tp"):
            k = k[2:]
        return ids.get(k)

    def _apply_radar_eval_state(self, radar: dict) -> None:
        """Compat shim: mark breathing engaged; no legacy RADAR_ARM DingTalk."""
        if not radar:
            return
        self._init_adverse_radar_fields()
        if radar.get("activated") or radar.get("armed") or radar.get("current_sl"):
            self.radar_activated = True
            self.radar_latched = True
        sc = int(radar.get("step_count") or 0)
        if sc > int(getattr(self, "radar_step_count", 0) or 0):
            self.radar_step_count = sc

    def _reset_adverse_radar(self, *, keep_tv_sl: bool = True) -> None:
        preserved = float(getattr(self, "tv_sl", 0) or 0) if keep_tv_sl else 0.0
        preserved_tv = float(getattr(self, "_tv_hard_sl_price", 0) or 0) if keep_tv_sl else 0.0
        preserved_frozen = float(getattr(self, "_frozen_hard_stop_px", 0) or 0) if keep_tv_sl else 0.0
        preserved_initial_stop = float(getattr(self, "initial_stop", 0) or 0) if keep_tv_sl else 0.0
        preserved_initial_atr = float(getattr(self, "initial_atr", 0) or 0) if keep_tv_sl else 0.0
        if keep_tv_sl and preserved_tv <= 0 and preserved > 0:
            preserved_tv = preserved
        if keep_tv_sl and preserved_frozen <= 0 and preserved_tv > 0:
            preserved_frozen = preserved_tv
        if keep_tv_sl and preserved_initial_stop <= 0 and preserved > 0:
            preserved_initial_stop = preserved
        self.adverse_sl_armed = False
        self.adverse_sl_prices = []
        self.adverse_consumed_tiers = []
        self._adverse_last_repair_ts = 0.0
        self.adverse_arm_dingtalk_sent = False
        self._pending_adverse_algo_ids = []
        self.radar_latched = False
        self.radar_activated = False
        self.radar_step_count = 0
        self._atr_refreshed_at = 0.0
        self._tp_placed_at = {}
        self._defense_order_ids = {}
        self._radar_arm_dingtalk_sent = False
        self._radar_path_ok_streak = 0
        self._last_radar_arm_meta = {}
        self.breakeven_phase = False
        self.remaining_qty_pct = 1.0
        self._last_breath_trail_alert_sl = 0.0
        _can = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        self.breathing_coefficient = cold_start_multiplier(profile_for_symbol(_can))
        self.breath_ratio_history = []
        self.atr_1h = 0.0
        self.breath_smooth_ratio = 1.0
        self.atr_scenario = ATR_SCENARIO_PENDING
        self.tp3_limit_active = False
        self._temp_tv_stop_active = False
        self.tv_sl = preserved
        self._tv_hard_sl_price = preserved_tv
        self._frozen_hard_stop_px = preserved_frozen
        self.initial_stop = preserved_initial_stop
        self.initial_atr = preserved_initial_atr
        if not keep_tv_sl:
            self._vps_hard_sl_meta = {}
            self.initial_stop = 0.0
            self.initial_atr = 0.0
            self.current_sl = 0.0
            self._tv_atr_ref = 0.0
            self._frozen_hard_stop_px = 0.0
            self._tv_hard_sl_price = 0.0

    def _clear_position_local_state(self) -> None:
        """Immediately wipe all breathing/position book fields after confirmed flat.

        Must not leave watched_entry / best_price / side residue — that polluted
        HARD_SL_MISSING (side=None + stale entry) and next-open stop logic.
        """
        self._init_adverse_radar_fields()
        if hasattr(self, "_reset_adverse_radar"):
            self._reset_adverse_radar(keep_tv_sl=False)
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.initial_qty = 0.0
        self.base_qty = 0.0
        self.add_count = 0
        self.current_side = None
        self.best_price = 0.0
        self.current_sl = 0.0
        self.initial_stop = 0.0
        self.initial_atr = 0.0
        self.breakeven_phase = False
        self.remaining_qty_pct = 1.0
        _can = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        self.breathing_coefficient = cold_start_multiplier(profile_for_symbol(_can))
        self.breath_ratio_history = []
        self.atr_1h = 0.0
        self.breath_smooth_ratio = 1.0
        self.atr_scenario = ATR_SCENARIO_PENDING
        self.tp3_limit_active = False
        self._temp_tv_stop_active = False
        self._tv_atr_ref = 0.0
        self.tv_sl = 0.0
        self._tv_hard_sl_price = 0.0
        self._frozen_hard_stop_px = 0.0
        self.consumed_tp_levels = []
        if hasattr(self, "_tp_fill_dingtalk_levels"):
            self._tp_fill_dingtalk_levels = set()
        self.current_trade_id = None
        self.trade_opened_at = None
        self.radar_latched = False
        self.radar_activated = False
        self.radar_step_count = 0

    def _latch_radar(self) -> None:
        """Once radar arms, never revert to hard-only defense until flat."""
        self._init_adverse_radar_fields()
        if not self.radar_latched:
            self.radar_latched = True
            logger.info(
                "[User %s] 📌 雷达已锁定 — 回调不回退硬止损·只准前进",
                getattr(self, "user_id", "?"),
            )

    def _is_radar_engaged(self) -> bool:
        """Radar latched (confirmed path/TP) — SL>entry alone is not enough."""
        self._init_adverse_radar_fields()
        if self.radar_latched:
            return True
        # Only treat SL-above-entry as engaged when we already latched this trade
        # (legacy sessions may have current_sl without latch — do not re-arm on that)
        return False

    def _clear_premature_radar_arm(self, curr_px: float, reason: str) -> None:
        """
        DEPRECATED no-op: 雷达挂上后只准前进、禁止解除。
        历史「路径回撤→撤雷达」已废除；误挂靠开仓宽限+双确认防呆，不靠事后撤销。
        """
        self._init_adverse_radar_fields()
        logger.info(
            "[User %s] ⏭️ 忽略雷达解除请求（只前进不撤）| px=%.2f | %s | latched=%s",
            getattr(self, "user_id", "?"),
            float(curr_px or 0),
            reason,
            bool(getattr(self, "radar_latched", False)),
        )
        return
    def _infer_radar_latched_from_state(self) -> None:
        """Backward compat: restore latch only when TP1+ actually filled (qty-backed)."""
        if getattr(self, "radar_latched", False):
            return
        # Never infer latch from current_sl > entry alone (tight TP1 noise / clamped BE)
        from app.core.vps_radar_stages import tp1_filled_from_consumed
        consumed = list(getattr(self, "consumed_tp_levels", []) or [])
        if not tp1_filled_from_consumed(consumed):
            return
        # Guard: do not latch if position still looks like full open (stale/false consume)
        anchor = float(getattr(self, "initial_qty", 0) or getattr(self, "watched_qty", 0) or 0)
        live = float(getattr(self, "watched_qty", 0) or 0)
        if anchor > 0 and live > 0:
            from app.core.position_qty_tolerance import tp_slice_qty_tolerance
            is_dc = getattr(self, "exchange_id", "") == "deepcoin"
            if abs(live - anchor) <= tp_slice_qty_tolerance(anchor, is_contracts=is_dc):
                self.consumed_tp_levels = []
                self.radar_latched = False
                return
        self.radar_latched = True

    def _hard_stop_label(self) -> str:
        return "硬止损"

    def _recompute_vps_hard_sl(
        self,
        entry_px: float | None = None,
        *,
        payload: dict | None = None,
        side: str | None = None,
    ) -> dict:
        """Authoritative hard SL = breathing initial stop (entry ± 1.5×ATR).

        initial_atr prefers TV webhook ``atr`` (frozen at open). VPS 90m is
        fallback only when TV atr is missing. TV stop_loss never hung as stop.
        """
        self._init_adverse_radar_fields()
        entry = float(
            entry_px
            or getattr(self, "watched_entry", 0)
            or getattr(self, "tv_price", 0)
            or 0
        )
        if payload:
            entry = float(payload.get("price") or entry or 0)

        # Prefer TV atr → frozen initial_atr
        atr = 0.0
        atr_source = "none"
        if payload:
            try:
                atr = float(payload.get("atr") or 0)
            except (TypeError, ValueError):
                atr = 0.0
            if atr > 0:
                atr_source = "tv_webhook"
                self._tv_atr_ref = atr
        if atr <= 0:
            atr = float(getattr(self, "_tv_atr_ref", 0) or 0)
            if atr > 0:
                atr_source = "tv_atr_ref"
        if atr <= 0:
            atr = float(getattr(self, "initial_atr", 0) or 0)
            if atr > 0:
                atr_source = "initial_atr"
        snap: dict[str, Any] = {}
        if atr <= 0:
            # Fallback: VPS 90m market engine
            snap = self._pull_vps_market_indicators(force=True)
            atr = float(snap.get("atr") or 0) or float(getattr(self, "current_atr", 0) or 0)
            if atr > 0:
                atr_source = "vps_90m_fallback"
        atr = resolve_atr(atr) if atr > 0 else 0.0
        if atr > 0:
            self.current_atr = atr
        if float(snap.get("adx") or 0) > 0:
            self.current_adx = resolve_adx(snap.get("adx"))
        side_u = side or getattr(self, "current_side", None)
        if not side_u and payload:
            act = str(payload.get("action") or "").upper()
            if "LONG" in act:
                side_u = "LONG"
            elif "SHORT" in act:
                side_u = "SHORT"
            elif payload.get("side"):
                side_u = str(payload.get("side")).upper()

        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        stop = (
            compute_initial_stop(entry, str(side_u or ""), atr, symbol=sym)
            if atr > 0 else 0.0
        )
        hang = apply_stop_order_buffer(side_u, stop, sym) if stop > 0 else 0.0
        meta = {
            "source": "breathing_initial",
            "stop_price": float(stop or 0),
            "hang_stop": float(hang or 0),
            "entry": entry,
            "side": side_u,
            "atr": atr,
            "atr_source": atr_source,
            "breathing_coefficient": resolve_breathing_coef(
                getattr(self, "breathing_coefficient", None), sym
            ),
            "initial_sl_atr": 1.5,
            "symbol": sym,
            "market_source": snap.get("source") if snap else atr_source,
            "bars_90": snap.get("bars_90") if snap else None,
        }
        if stop > 0:
            # Logical stop in state; exchange hang uses ±0.3 buffer at place time.
            self.initial_stop = float(stop)
            self.current_sl = float(stop)
            self._tv_hard_sl_price = float(stop)
            tv_sl_ref = None
            if payload:
                try:
                    tv_sl_ref = float(
                        payload.get("stop_loss") or payload.get("tv_sl") or 0
                    ) or None
                except (TypeError, ValueError):
                    tv_sl_ref = None
            if tv_sl_ref and tv_sl_ref > 0:
                # tv_sl / _tv_stop_loss_ref: Pine stop_loss ONLY (sizing + ATR compare).
                self.tv_sl = float(tv_sl_ref)
                self._tv_stop_loss_ref = float(tv_sl_ref)
                self._pending_open_tv_sl = float(tv_sl_ref)
            if float(getattr(self, "initial_atr", 0) or 0) <= 0:
                self.initial_atr = atr
            if float(getattr(self, "initial_atr", 0) or 0) <= 0 or not (
                bool(getattr(self, "monitoring", False))
                or float(getattr(self, "watched_qty", 0) or 0) > 0
            ):
                self.current_atr = atr
            self._vps_hard_sl_meta = meta
            logger.info(
                "呼吸止损: entry=%.2f side=%s atr=%.4f (%s) → stop=%.2f hang=%.2f | %s",
                entry, side_u, atr, atr_source, stop, hang, meta,
            )
            self._maybe_alert_atr_mismatch(entry, tv_sl_ref, atr)
        else:
            self._vps_hard_sl_meta = meta
            live_open = (
                bool(getattr(self, "monitoring", False))
                or float(getattr(self, "watched_qty", 0) or 0) > 0
            ) and side_u in ("LONG", "SHORT") and entry > 0
            logger.error(
                "呼吸止损缺失: entry=%.2f side=%s atr=%.4f — 无法计算初始止损 | %s",
                entry, side_u, atr, meta,
            )
            if live_open and hasattr(self, "_alert"):
                try:
                    self._alert(
                        "critical",
                        "HARD_SL_MISSING",
                        "呼吸止损缺失·禁止漏挂",
                        f"entry={entry:.2f} side={side_u} atr={atr} — 无法计算呼吸初始止损",
                        {"entry": entry, "side": side_u, "meta": meta,
                         "exchange": getattr(self, "exchange_id", None)},
                    )
                except Exception:
                    pass
        return meta

    def _apply_tv_sl_from_payload(self, payload: dict | None) -> float | None:
        """Ignore TV stop_loss/atr/adx for decisions; pull VPS indicators and recompute stop at open."""
        if not payload:
            return None
        self._init_adverse_radar_fields()
        # Live breathing position: never reset stop from TV / mid-trade atr
        live_breath = (
            float(getattr(self, "initial_stop", 0) or 0) > 0
            and float(getattr(self, "initial_atr", 0) or 0) > 0
            and (
                bool(getattr(self, "monitoring", False))
                or float(getattr(self, "watched_qty", 0) or 0) > 0
            )
        )
        if live_breath:
            # Soft-refresh ADX only from VPS; do not touch stops/initial_atr
            self._pull_vps_market_indicators(force=False)
            px = float(
                getattr(self, "current_sl", 0)
                or getattr(self, "initial_stop", 0)
                or getattr(self, "tv_sl", 0)
                or 0
            )
            return px if px > 0 else None
        # Intentionally ignore stop_loss / tv_sl / atr / adx for stop price
        meta = self._recompute_vps_hard_sl(payload=payload)
        px = float(meta.get("stop_price") or 0)
        return px if px > 0 else None

    def _clamp_radar_sl_to_tv_floor(self, sl: float) -> float:
        """Radar may tighten only; never looser than frozen hard stop."""
        hard = self._frozen_hard_px()
        side = str(getattr(self, "current_side", "") or "").upper()
        try:
            px = float(sl or 0)
        except (TypeError, ValueError):
            return sl
        if hard <= 0 or px <= 0 or side not in ("LONG", "SHORT"):
            return px if px > 0 else sl
        if side == "LONG":
            return max(px, hard)
        return min(px, hard)

    def _defense_mark_price(self) -> float:
        if hasattr(self, "_current_tp_price"):
            try:
                return float(self._current_tp_price() or 0)
            except (TypeError, ValueError):
                pass
        client = getattr(self, "client", None)
        symbol = getattr(self, "symbol", None)
        if client and symbol and hasattr(client, "get_current_price"):
            try:
                return float(client.get_current_price(symbol) or 0)
            except (TypeError, ValueError):
                pass
        return 0.0

    def _mark_price_trusted(self, curr_px: float) -> bool:
        px = float(curr_px or 0)
        if px <= 0:
            return False
        entry = float(getattr(self, "watched_entry", 0) or 0)
        if entry <= 0:
            return True
        return abs(px - entry) / entry <= 0.35

    def _market_safe_stop_price(self, stop_price: float, curr_px: float | None = None) -> float:
        px = float(curr_px if curr_px is not None else self._defense_mark_price())
        side = getattr(self, "current_side", None)
        sl = float(stop_price or 0)
        if sl <= 0 or px <= 0 or not self._mark_price_trusted(px):
            return sl
        return clamp_stop_market_safe(sl, px, side)

    def _uses_dual_stop_track(self) -> bool:
        """Whitepaper: hard stop + radar coexist permanently on all exchanges."""
        return True

    def _effective_radar_sl_for_merge(self) -> float:
        sl = float(getattr(self, "current_sl", 0) or 0)
        if sl > 0:
            return sl
        return self._exchange_stop_px()

    def _merged_stop_price(self, radar_sl: float | None = None) -> float:
        """Legacy single-slot hang price — dual track uses hard/radar separately."""
        if self._uses_dual_stop_track():
            hard = self._frozen_hard_px()
            if hard > 0:
                return self._exchange_hang_stop_px(hard)
        if radar_sl is not None and float(radar_sl or 0) > 0:
            logical = float(radar_sl)
        else:
            logical = float(
                getattr(self, "current_sl", 0)
                or getattr(self, "initial_stop", 0)
                or getattr(self, "_tv_hard_sl_price", 0)
                or 0
            )
        if logical <= 0:
            return 0.0
        return self._exchange_hang_stop_px(logical)

    def _shield_tier_prices(self) -> set[float]:
        """Hard-stop trigger prices only (never radar current_sl in dual mode)."""
        prices = set(self._adverse_tier_stop_prices())
        for px in (self.adverse_sl_prices or []):
            try:
                p = round(float(px), 2)
                if p > 0:
                    prices.add(p)
            except (TypeError, ValueError):
                continue
        hard_attrs = ("_frozen_hard_stop_px", "_tv_hard_sl_price", "tv_sl")
        if not self._uses_dual_stop_track():
            hard_attrs = ("current_sl", "initial_stop", "tv_sl", "_tv_hard_sl_price", "_frozen_hard_stop_px")
        for attr in hard_attrs:
            try:
                p = round(float(getattr(self, attr, 0) or 0), 2)
            except (TypeError, ValueError):
                continue
            if p > 0:
                prices.add(p)
        return prices

    def _adverse_tier_stop_prices(self) -> set[float]:
        if self._uses_dual_stop_track():
            prices: set[float] = set()
            hard = self._frozen_hard_px()
            if hard > 0:
                prices.add(round_price(hard))
                hang = self._exchange_hang_stop_px(hard)
                if hang > 0:
                    prices.add(round_price(hang))
            return prices
        merged = self._merged_stop_price()
        if merged > 0:
            return {merged}
        tv_sl = float(getattr(self, "tv_sl", 0) or 0)
        if tv_sl > 0:
            return {round_price(tv_sl)}
        return set()

    def _count_live_stop_orders(self) -> int:
        """How many conditional/hard SL orders are live (max=2 in dual track).

        Uses unfiltered STOP* collection — tier-price filter under-counts and was the
        root of same-price STOP stacking (empty view → place again).

        Returns -1 on fetch failure (fail-closed: callers must refuse place).
        """
        try:
            return len(self._collect_all_stop_like_orders() or [])
        except Exception:
            return -1

    def _collect_all_stop_like_orders(self) -> list[dict]:
        """Every STOP/STOP_MARKET/algo stop (+ hard-SL LIMIT) on this symbol — no tier filter."""
        symbol = getattr(self, "symbol", None)
        client = getattr(self, "client", None)
        if not symbol or not client:
            return []
        if getattr(self, "exchange_id", "") == "deepcoin":
            return list(self._collect_adverse_stop_orders() or [])

        if hasattr(client, "_invalidate_book_cache"):
            try:
                client._invalidate_book_cache("count_all_stops")
            except Exception:
                pass

        orders: list[dict] = []
        seen: set[str | int] = set()
        try:
            close_side = str(self._adverse_close_side() or "").upper()
        except Exception:
            side = str(getattr(self, "current_side", "") or "").upper()
            close_side = "SELL" if side == "LONG" else ("BUY" if side == "SHORT" else "")

        def _add(o: dict) -> None:
            oid = o.get("algoId") or o.get("orderId") or o.get("ordId")
            if oid is not None and oid in seen:
                return
            if oid is not None:
                seen.add(oid)
            orders.append(o)

        for o in client.get_open_orders(symbol) or []:
            if not isinstance(o, dict):
                continue
            if _is_stop_market_like(o):
                order_side = str(o.get("side", "")).upper()
                if close_side and order_side and order_side != close_side:
                    continue
                _add(o)
                continue
            if str(o.get("type") or "").upper() == "LIMIT" and self._is_hard_sl_limit_order(o):
                _add(o)

        # Pending algo ids — fetch by id without tier filter (lag cover)
        for aid in list(getattr(self, "_pending_adverse_algo_ids", None) or []):
            try:
                aid_int = int(aid)
            except (TypeError, ValueError):
                continue
            if aid_int in seen:
                continue
            try:
                o = client.get_algo_order(symbol, aid_int) if hasattr(client, "get_algo_order") else None
            except Exception:
                o = None
            if o and isinstance(o, dict) and _is_stop_market_like(o):
                _add(o)

        if hasattr(client, "get_open_algo_orders"):
            try:
                for o in client.get_open_algo_orders(symbol=symbol) or []:
                    if isinstance(o, dict) and _is_stop_market_like(o):
                        order_side = str(o.get("side", "")).upper()
                        if close_side and order_side and order_side != close_side:
                            continue
                        _add(o)
            except Exception as e:
                # Partial regular + failed algo → unknown book (do not under-count)
                raise RuntimeError(f"algo_book_unknown:{e}") from e
        return orders

    def _cancel_binance_all_close_stops(self) -> int:
        """Cancel ALL stop-like close orders (flat / pre-open cleanup).

        Dual-track radar replace must NOT call this — use `_cancel_radar_stop_orders`.
        Hard stop is only wiped here (position flat / open clean-slate).
        """
        symbol = getattr(self, "symbol", None)
        client = getattr(self, "client", None)
        if not symbol or not client:
            return 0
        cancelled = 0
        seen: set[str | int] = set()
        cancelled_ids: set[str | int] = set()
        tier_prices = self._shield_tier_prices()

        def _cancel_one(o: dict) -> bool:
            nonlocal cancelled
            oid = o.get("algoId") or o.get("orderId") or o.get("ordId")
            if oid is None or oid in seen:
                return False
            seen.add(oid)
            ok = bool(client.cancel_order(symbol, int(oid)))
            if ok:
                cancelled += 1
                cancelled_ids.add(oid)
            time.sleep(0.2)
            return ok

        # Pass 1: unfiltered stop-like (prevents same-price stacks surviving tier filter)
        for o in self._collect_all_stop_like_orders() or []:
            _cancel_one(o)
        # Pass 2: tier-aware adverse collector (hard-SL LIMIT at current_sl)
        for o in self._collect_adverse_stop_orders() or []:
            _cancel_one(o)
        # Pass 3: pending algo ids
        for o in self._collect_pending_adverse_algo_orders(tier_prices or set()):
            _cancel_one(o)

        if hasattr(client, "_invalidate_book_cache"):
            try:
                client._invalidate_book_cache("cancel_all_close_stops")
            except Exception:
                pass
        time.sleep(0.25)
        for o in self._collect_all_stop_like_orders() or []:
            _cancel_one(o)

        # Only drop pending ids we actually canceled (partial cancel must keep survivors)
        if cancelled_ids and hasattr(self, "_pending_adverse_algo_ids"):
            try:
                self._pending_adverse_algo_ids = [
                    x for x in (self._pending_adverse_algo_ids or [])
                    if x not in cancelled_ids
                ]
            except Exception:
                pass
        remaining = self._count_live_stop_orders()
        if remaining > 0:
            logger.error(
                "[User %s] %s cancel-all close stops left %s live — refuse silent place",
                getattr(self, "user_id", "?"),
                getattr(self, "canonical_symbol", symbol),
                remaining,
            )
        return cancelled

    def _sync_binance_merged_stop(
        self,
        live_qty: float,
        *,
        radar_sl: float | None = None,
        force_replace: bool = False,
        at_open: bool = False,
    ) -> dict[str, Any]:
        """Route A · Binance/OKX/Gate：单 closePosition = max/min(tv_sl, 雷达)。"""
        live_qty = self._resolve_adverse_live_qty(live_qty)
        if live_qty <= 0:
            return {"armed": False, "reason": "no_live_position", "live_qty": 0}

        # 开仓必须换掉残留条件单，禁止 live_already_aligned 保留旧紧止损
        if at_open:
            force_replace = True

        effective = self._merged_stop_price(radar_sl)
        if effective <= 0:
            return {"armed": False, "reason": "no_tv_sl_or_radar"}

        side = getattr(self, "current_side", None)
        open_stops = self._collect_adverse_stop_orders()
        live_stop_px = (
            _adverse_defense_price(open_stops[0]) if open_stops else 0.0
        )
        if live_stop_px > 0 and effective > 0:
            if abs(effective - live_stop_px) > ADVERSE_STOP_TOLERANCE:
                force_replace = True
            elif side == "LONG" and effective > live_stop_px + ADVERSE_STOP_TOLERANCE:
                force_replace = True
            elif side == "SHORT" and effective < live_stop_px - ADVERSE_STOP_TOLERANCE:
                force_replace = True

        curr_px = self._defense_mark_price()
        raw_effective = effective
        if curr_px > 0 and self._mark_price_trusted(curr_px):
            if stop_would_trigger_immediately(effective, curr_px, side):
                audit_early = self._audit_adverse_shield_live([{
                    "tier_pct": TV_SL_TIER_MARKER,
                    "stop_price": effective,
                    "qty": self._adverse_round_qty(live_qty),
                    "level": 1,
                    "source": "merged",
                }])
                if audit_early.get("aligned"):
                    open_stops = self._collect_adverse_stop_orders()
                    live_px = (
                        _adverse_defense_price(open_stops[0])
                        if open_stops
                        else float(getattr(self, "tv_sl", 0) or 0)
                    )
                    self.adverse_sl_armed = True
                    self.adverse_sl_prices = [live_px] if live_px > 0 else []
                    return {
                        "armed": True,
                        "aligned": True,
                        "merged": True,
                        "stop_price": live_px,
                        "tv_sl": float(getattr(self, "tv_sl", 0) or 0),
                        "placed": 0,
                        "skipped": "stop_above_mark_deferred",
                        "curr_px": curr_px,
                        "requested_stop": raw_effective,
                        "label": self._hard_stop_label(),
                    }
                effective = self._market_safe_stop_price(effective, curr_px)
                if effective <= 0:
                    return {
                        "armed": False,
                        "reason": "stop_unsafe_no_market_gap",
                        "curr_px": curr_px,
                        "requested_stop": raw_effective,
                    }
            else:
                effective = self._market_safe_stop_price(effective, curr_px)

        plan = [{
            "tier_pct": TV_SL_TIER_MARKER,
            "stop_price": effective,
            "qty": self._adverse_round_qty(live_qty),
            "level": 1,
            "source": "merged",
        }]
        audit = self._audit_adverse_shield_live(plan)
        if audit.get("needs_purge_only") or audit.get("open_count", 0) > ADVERSE_MAX_STOP_ORDERS:
            purged = self._cancel_binance_all_close_stops()
            if purged:
                time.sleep(0.35)
                audit = self._audit_adverse_shield_live(plan)
        if audit.get("aligned") and not force_replace:
            # Even when "aligned", hard-cap at 1 stop — purge extras without re-placing.
            if int(audit.get("open_count") or 0) > ADVERSE_MAX_STOP_ORDERS:
                purged = self._cancel_binance_all_close_stops()
                time.sleep(0.35)
                placed = 1 if self._place_adverse_stop_slice(effective, live_qty) else 0
                audit = self._refresh_adverse_shield_audit(
                    plan, retries=ADVERSE_VERIFY_RETRIES, delay=ADVERSE_VERIFY_RETRY_DELAY_SEC,
                )
                self.adverse_sl_armed = bool(audit.get("aligned") or placed)
                self.adverse_sl_prices = [effective] if self.adverse_sl_armed else []
                return {
                    "armed": self.adverse_sl_armed,
                    "aligned": audit.get("aligned", False),
                    "merged": True,
                    "stop_price": effective,
                    "tv_sl": float(getattr(self, "tv_sl", 0) or 0),
                    "placed": placed,
                    "cancelled": purged,
                    "skipped": "purged_duplicate_then_rearm",
                    "label": self._hard_stop_label(),
                    **audit,
                }
            self.adverse_sl_armed = True
            self.adverse_sl_prices = [effective]
            return {
                "armed": True,
                "aligned": True,
                "merged": True,
                "stop_price": effective,
                "tv_sl": float(getattr(self, "tv_sl", 0) or 0),
                "placed": 0,
                "skipped": "live_already_aligned",
                "label": self._hard_stop_label(),
            }

        cancelled = self._cancel_binance_all_close_stops() if force_replace or not audit.get("aligned") else 0
        # Verify-before-place: never hang a second stop on a failed/partial cancel.
        time.sleep(0.3)
        leftover = self._count_live_stop_orders()
        if leftover < 0:
            logger.error(
                "[User %s] %s refuse place: stop book fetch failed after cancel",
                getattr(self, "user_id", "?"),
                getattr(self, "canonical_symbol", getattr(self, "symbol", "?")),
            )
            return {
                "armed": False,
                "aligned": False,
                "merged": True,
                "stop_price": effective,
                "placed": 0,
                "cancelled": cancelled,
                "skipped": "refuse_place_book_unknown",
                "label": self._hard_stop_label(),
            }
        if leftover > 0:
            cancelled += self._cancel_binance_all_close_stops()
            time.sleep(0.35)
            leftover = self._count_live_stop_orders()
        if leftover < 0 or leftover > 0:
            logger.error(
                "[User %s] %s refuse place: %s stop(s) still live after cancel",
                getattr(self, "user_id", "?"),
                getattr(self, "canonical_symbol", getattr(self, "symbol", "?")),
                leftover,
            )
            self.adverse_sl_armed = leftover >= 1
            self.adverse_sl_prices = [effective] if self.adverse_sl_armed else []
            if hasattr(self, "_alert"):
                try:
                    self._alert(
                        "critical",
                        "SL_DUP_BLOCK",
                        "止损重复·拒挂第二单",
                        f"{getattr(self, 'canonical_symbol', '')} 撤单后仍有 {leftover} 笔条件止损，已禁止再挂",
                        {"leftover": leftover, "stop_price": effective},
                    )
                except Exception:
                    pass
            return {
                "armed": self.adverse_sl_armed,
                "aligned": False,
                "merged": True,
                "stop_price": effective,
                "placed": 0,
                "cancelled": cancelled,
                "skipped": "refuse_place_leftover_stops",
                "leftover_stops": leftover,
                "label": self._hard_stop_label(),
            }

        placed = 1 if self._place_adverse_stop_slice(effective, live_qty) else 0
        if placed:
            audit = self._refresh_adverse_shield_audit(
                plan, retries=ADVERSE_VERIFY_RETRIES, delay=ADVERSE_VERIFY_RETRY_DELAY_SEC,
            )
            # Post-place hard cap: if book shows >1, wipe extras keep one.
            if int(audit.get("open_count") or 0) > ADVERSE_MAX_STOP_ORDERS:
                purged = self._purge_excess_adverse_stops(plan)
                if purged == 0:
                    # purge failed (e.g. algoId) — full cancel+rearm once
                    self._cancel_binance_all_close_stops()
                    time.sleep(0.35)
                    if self._count_live_stop_orders() == 0:
                        self._place_adverse_stop_slice(effective, live_qty)
                audit = self._refresh_adverse_shield_audit(
                    plan, retries=ADVERSE_VERIFY_RETRIES, delay=ADVERSE_VERIFY_RETRY_DELAY_SEC,
                )
        self.adverse_sl_armed = bool(audit.get("aligned") or placed)
        self.adverse_sl_prices = [effective] if self.adverse_sl_armed else []
        return {
            "armed": self.adverse_sl_armed,
            "aligned": audit.get("aligned", False),
            "merged": True,
            "stop_price": effective,
            "tv_sl": float(getattr(self, "tv_sl", 0) or 0),
            "placed": placed,
            "cancelled": cancelled,
            "label": self._hard_stop_label(),
            "order_style": getattr(self, "_last_hard_sl_order_style", None),
            "limit_price": self._hard_sl_limit_price(effective) if effective > 0 else 0.0,
            **audit,
        }

    def _resolve_adverse_live_qty(self, fallback_qty: float) -> float:
        """Always anchor adverse slices to exchange live position, not stale watched_qty."""
        if hasattr(self, "_resolve_live_qty"):
            try:
                return float(self._resolve_live_qty(fallback_qty))
            except TypeError:
                pass
        if hasattr(self, "_read_live_position_qty"):
            live, _ = self._read_live_position_qty()
            if live > 0:
                return float(live)
        pos = self._get_active_position() if hasattr(self, "_get_active_position") else None
        if pos:
            if getattr(self, "exchange_id", "") == "deepcoin":
                safe = getattr(self, "_safe_qty", lambda x: int(x))
                live = float(safe(pos.get("size", 0)))
            else:
                live = abs(float(pos.get("size", pos.get("positionAmt", 0)) or 0))
            if live > 0:
                return live
        return float(fallback_qty or 0)

    def _adverse_move_pct(self, curr_px: float) -> float:
        return adverse_move_pct(
            float(getattr(self, "watched_entry", 0) or 0),
            float(curr_px or 0),
            getattr(self, "current_side", None),
        )

    def _is_floating_profit(self, curr_px: float) -> bool:
        return is_floating_profit(
            float(getattr(self, "watched_entry", 0) or 0),
            float(curr_px or 0),
            getattr(self, "current_side", None),
        )

    def _qty_match_tol(self, old_qty: float = 0, new_qty: float = 0) -> float:
        return qty_drift_tolerance(
            old_qty,
            new_qty,
            is_contracts=getattr(self, "exchange_id", "") == "deepcoin",
        )

    def _adverse_round_qty(self, qty: float) -> float:
        if getattr(self, "exchange_id", "") == "deepcoin":
            safe = getattr(self, "_safe_qty", lambda x: int(x))
            return float(max(int(safe(qty)), 1))
        return round_quantity(qty)

    def _adverse_consumed_set(self) -> set[float]:
        return {round(float(t), 4) for t in (self.adverse_consumed_tiers or [])}

    def _compute_adverse_stop_plan(self, live_qty: float) -> list[dict[str, Any]]:
        hard = self._frozen_hard_px()
        tv_sl = hard if hard > 0 else float(getattr(self, "tv_sl", 0) or 0)
        return compute_adverse_stop_plan(
            float(self.watched_entry or 0),
            str(self.current_side or "LONG"),
            float(live_qty),
            round_qty_fn=self._adverse_round_qty,
            consumed_tiers=self._adverse_consumed_set(),
            tv_sl_price=tv_sl if tv_sl > 0 else None,
        )

    def _hard_stop_on_book(self, hard_px: float) -> bool:
        """True when a live stop sits near the frozen hard trigger."""
        if hard_px <= 0:
            return False
        hang = self._exchange_hang_stop_px(hard_px) or hard_px
        if hasattr(self, "_has_stop_sl_near"):
            try:
                near = self._has_stop_sl_near(hang)
                if near is True:
                    return True
                if near is False:
                    # also accept exact frozen trigger without buffer
                    near2 = self._has_stop_sl_near(hard_px)
                    return bool(near2)
            except Exception:
                pass
        try:
            for o in self._collect_adverse_stop_orders() or []:
                px = float(_adverse_defense_price(o) or 0)
                if px > 0 and abs(px - hang) <= ADVERSE_STOP_TOLERANCE:
                    return True
                if px > 0 and abs(px - hard_px) <= ADVERSE_STOP_TOLERANCE:
                    return True
        except Exception:
            pass
        return False

    def _sync_hard_stop_only(
        self,
        live_qty: float,
        *,
        at_open: bool = False,
        force_replace: bool = False,
    ) -> dict[str, Any]:
        """Place/verify frozen hard stop only — never cancel/reprice while in position.

        force_replace is ignored for price (whitepaper: hard price immutable).
        Qty resize: cancel hard-tier only then re-place same price with new qty.
        """
        live_qty = self._resolve_adverse_live_qty(live_qty)
        hard = self._frozen_hard_px()
        if live_qty <= 0:
            return {"armed": False, "reason": "no_live_position", "live_qty": 0, "label": self._hard_stop_label()}
        if hard <= 0:
            return {"armed": False, "reason": "no_frozen_hard", "label": self._hard_stop_label()}

        hang = self._exchange_hang_stop_px(hard)
        on_book = self._hard_stop_on_book(hard)
        if on_book and not force_replace:
            return {
                "armed": True,
                "aligned": True,
                "skipped": "live_already_aligned",
                "stop_price": hang,
                "hard_price": hard,
                "placed": 0,
                "label": self._hard_stop_label(),
            }

        # Qty resize or missing: cancel hard-tier orders only (never radar)
        if on_book and force_replace:
            try:
                self._cancel_adverse_stop_orders()
            except Exception as exc:
                logger.warning(
                    "[User %s] hard qty resize cancel failed: %s",
                    getattr(self, "user_id", "?"),
                    exc,
                )
            time.sleep(0.2)
        elif not on_book:
            # Missing hard — place without wiping radar
            pass

        # Refuse if already at max stops and hard still missing (book pollution)
        live_n = self._count_live_stop_orders()
        if live_n < 0:
            return {
                "armed": False,
                "reason": "book_unknown",
                "skipped": "refuse_place_book_unknown",
                "label": self._hard_stop_label(),
            }

        placed = bool(self._place_adverse_stop_slice(hang, live_qty))
        if not placed and self._hard_stop_on_book(hard):
            return {
                "armed": True,
                "aligned": True,
                "skipped": "live_already_aligned",
                "stop_price": hang,
                "hard_price": hard,
                "placed": 0,
                "label": self._hard_stop_label(),
            }
        return {
            "armed": placed,
            "placed": 1 if placed else 0,
            "stop_price": hang,
            "hard_price": hard,
            "at_open": at_open,
            "label": self._hard_stop_label(),
            "order_style": getattr(self, "_last_hard_sl_order_style", None),
        }

    def _sync_tv_hard_stop(
        self,
        live_qty: float,
        *,
        at_open: bool = False,
        force_replace: bool = False,
    ) -> dict[str, Any]:
        """Arm permanent hard stop (dual) or legacy merged single-slot."""
        if self._uses_dual_stop_track():
            return self._sync_hard_stop_only(
                live_qty, at_open=at_open, force_replace=force_replace,
            )
        radar = float(getattr(self, "current_sl", 0) or 0) or None
        return self._sync_binance_merged_stop(
            live_qty, radar_sl=radar, force_replace=force_replace, at_open=at_open,
        )

    def _handle_update_sl(self, payload: dict) -> dict[str, Any]:
        """UPDATE_SL → ignore TV stop price; soft-refresh ADX from VPS market engine only."""
        self._init_adverse_radar_fields()
        adx_before = float(getattr(self, "current_adx", 0) or 0)
        snap = self._pull_vps_market_indicators(force=False)
        tv_sl_ignored = parse_tv_sl(payload.get("tv_sl") or payload.get("stop_loss"))
        detail = {
            "action": "UPDATE_SL",
            "ignored": True,
            "ignored_tv_sl": float(tv_sl_ignored or 0) or None,
            "current_sl": float(getattr(self, "current_sl", 0) or 0),
            "current_adx": float(getattr(self, "current_adx", 0) or 0),
            "adx_before": adx_before,
            "market_source": snap.get("source"),
            "note": "呼吸止损不采纳TV止损价；ADX仅来自VPS行情引擎",
        }
        self._log("UPDATE_SL", "忽略TV止损价·呼吸止损自管", detail)
        if hasattr(self, "_alert") and float(getattr(self, "current_adx", 0) or 0) != adx_before:
            self._alert(
                "info",
                "UPDATE_SL",
                "呼吸止损·ADX已刷新",
                f"ADX {adx_before:.1f}→{float(self.current_adx):.1f} | SL@{float(getattr(self, 'current_sl', 0) or 0):.2f}",
                detail,
            )
        return {"status": "ignored", "reason": "breathing_owns_sl", "action": "UPDATE_SL", "detail": detail}

    def _live_side_from_pos(self, pos: dict | None) -> str | None:
        if not pos:
            return None
        side = str(pos.get("side") or "").upper().strip()
        if side in ("LONG", "SHORT"):
            return side
        ps = str(pos.get("posSide") or "").lower().strip()
        if ps == "long":
            return "LONG"
        if ps == "short":
            return "SHORT"
        cur = str(getattr(self, "current_side", "") or "").upper().strip()
        return cur if cur in ("LONG", "SHORT") else None

    def _place_updated_tp_orders(self, live_qty: float, entry: float) -> int:
        """Re-place remaining TP limits only — never touches hard SL / radar stops."""
        if getattr(self, "exchange_id", "") == "deepcoin" and hasattr(self, "_rebuild_defenses"):
            return int(self._rebuild_defenses(live_qty, entry, dynamic_sl=None) or 0)
        if hasattr(self, "_rebuild_tp_limit_orders"):
            return int(self._rebuild_tp_limit_orders(live_qty, entry, dynamic_sl=None) or 0)
        if hasattr(self, "_rebuild_defenses"):
            result = self._rebuild_defenses(live_qty, entry, dynamic_sl=None)
            if isinstance(result, dict):
                return int(result.get("matched") or result.get("placed") or 0)
            return int(result or 0)
        return 0

    def _handle_update_tp(self, payload: dict) -> dict[str, Any]:
        """TV v6.9.108 动能升级：只替换 TP123 限价，绝不触碰硬止损 / 雷达."""
        from app.core.symbol_precision import normalize_tv_targets
        from app.core.tp_defense_reconcile import tp_price_matches
        from app.services.trading_alerts import resolve_exchange_theme

        side = str(payload.get("side") or "").upper().strip()
        new_tps = normalize_tv_targets([
            payload.get("tv_tp1", 0),
            payload.get("tv_tp2", 0),
            payload.get("tv_tp3", 0),
        ])
        old_tps = list(getattr(self, "tv_tps", []) or [0.0, 0.0, 0.0])
        theme = resolve_exchange_theme(getattr(self, "exchange_id", "binance"))
        detail: dict[str, Any] = {
            "action": "UPDATE_TP",
            "side": side,
            "old_tv_tps": old_tps,
            "new_tv_tps": list(new_tps),
            "exchange": getattr(self, "exchange_id", None),
            "hard_sl_untouched": True,
            "radar_untouched": True,
            "vps_sl": self._exchange_stop_px(),
            "radar_sl": float(getattr(self, "current_sl", 0) or 0),
        }

        if side not in ("LONG", "SHORT"):
            msg = "UPDATE_TP 忽略：side 无效"
            self._log("UPDATE_TP", msg, detail)
            return {"status": "skipped", "reason": "invalid_side", "action": "UPDATE_TP", "detail": detail}

        if not all(float(t or 0) > 0 for t in new_tps[:3]):
            msg = "UPDATE_TP 忽略：缺少有效新 TP 价格"
            self._log("UPDATE_TP", msg, detail)
            return {"status": "skipped", "reason": "invalid_tps", "action": "UPDATE_TP", "detail": detail}

        pos = self._get_active_position() if hasattr(self, "_get_active_position") else None
        live_side = self._live_side_from_pos(pos)
        if not pos or not live_side:
            msg = "UPDATE_TP 忽略：当前无持仓"
            self._log("UPDATE_TP", msg, detail)
            return {"status": "skipped", "reason": "no_position", "action": "UPDATE_TP", "detail": detail}

        if live_side != side:
            detail["live_side"] = live_side
            msg = f"UPDATE_TP 忽略：方向不匹配 TV={side} 实盘={live_side}"
            self._log("UPDATE_TP", msg, detail)
            return {"status": "skipped", "reason": "side_mismatch", "action": "UPDATE_TP", "detail": detail}

        if hasattr(self, "_safe_qty"):
            live_qty = float(self._safe_qty(pos.get("size", 0)))
        else:
            live_qty = float(pos.get("size") or 0)
        entry = float(pos.get("entry_price") or getattr(self, "watched_entry", 0) or 0)
        detail["qty"] = live_qty
        detail["entry"] = entry

        curr_px = 0.0
        if hasattr(self, "_defense_mark_price"):
            try:
                curr_px = float(self._defense_mark_price() or 0)
            except (TypeError, ValueError):
                curr_px = 0.0
        if curr_px <= 0 and hasattr(self, "_current_tp_price"):
            try:
                curr_px = float(self._current_tp_price() or 0)
            except (TypeError, ValueError):
                curr_px = 0.0
        detail["mark_price"] = curr_px

        tp1 = float(new_tps[0] or 0)
        if curr_px > 0:
            if side == "LONG" and tp1 <= curr_px:
                msg = f"UPDATE_TP 忽略：多头新TP1={tp1:.2f} ≤ 市价 {curr_px:.2f}"
                self._log("UPDATE_TP", msg, {**detail, "reject": "tp1_not_above_mark"})
                self._alert(
                    "warning", "UPDATE_TP", f"{theme['accent']} 动能止盈升级拒绝", msg, detail,
                )
                return {
                    "status": "skipped",
                    "reason": "tp1_not_above_mark",
                    "action": "UPDATE_TP",
                    "detail": detail,
                }
            if side == "SHORT" and tp1 >= curr_px:
                msg = f"UPDATE_TP 忽略：空头新TP1={tp1:.2f} ≥ 市价 {curr_px:.2f}"
                self._log("UPDATE_TP", msg, {**detail, "reject": "tp1_not_below_mark"})
                self._alert(
                    "warning", "UPDATE_TP", f"{theme['accent']} 动能止盈升级拒绝", msg, detail,
                )
                return {
                    "status": "skipped",
                    "reason": "tp1_not_below_mark",
                    "action": "UPDATE_TP",
                    "detail": detail,
                }

        same = True
        for i in range(3):
            old = float(old_tps[i] if i < len(old_tps) else 0)
            new = float(new_tps[i] if i < len(new_tps) else 0)
            if not tp_price_matches(old, new):
                same = False
                break
        if same:
            msg = f"UPDATE_TP 幂等跳过：TP 未变 {new_tps}"
            self._log("UPDATE_TP", msg, {**detail, "idempotent": True})
            return {
                "status": "ok",
                "reason": "idempotent",
                "action": "UPDATE_TP",
                "detail": detail,
            }

        # Apply new TP targets only after validation (hard SL / radar untouched).
        self.tv_tps = list(new_tps)
        self.current_side = side
        if live_qty > 0:
            self.watched_qty = live_qty
        if entry > 0:
            self.watched_entry = entry

        if not hasattr(self, "_cancel_all_tp_limit_orders"):
            msg = "UPDATE_TP 失败：缺少撤销止盈能力"
            self._log("UPDATE_TP", msg, detail)
            self.tv_tps = old_tps
            return {"status": "error", "reason": "no_cancel_tp", "action": "UPDATE_TP", "detail": detail}

        try:
            cancelled = int(self._cancel_all_tp_limit_orders() or 0)
        except Exception as exc:
            detail["cancel_error"] = str(exc)
            msg = f"UPDATE_TP 取消旧止盈失败，未挂新单: {exc}"
            self._log("UPDATE_TP", msg, detail)
            self.tv_tps = old_tps
            self._alert("error", "UPDATE_TP", f"{theme['accent']} 动能止盈升级失败", msg, detail)
            return {"status": "error", "reason": "cancel_failed", "action": "UPDATE_TP", "detail": detail}

        detail["cancelled_tp"] = cancelled
        time.sleep(0.25)

        placed = 0
        last_err = None
        for attempt in range(3):
            try:
                placed = self._place_updated_tp_orders(live_qty, entry)
                if placed > 0:
                    break
            except Exception as exc:
                last_err = str(exc)
                logger.warning("UPDATE_TP place attempt %s failed: %s", attempt + 1, exc)
            time.sleep(0.2)

        detail["placed_tp"] = placed
        if last_err:
            detail["place_error"] = last_err

        if placed <= 0:
            msg = f"UPDATE_TP 挂新止盈失败（已撤旧单 {cancelled}）"
            self._log("UPDATE_TP", msg, detail)
            self._alert("error", "UPDATE_TP", f"{theme['accent']} 动能止盈升级失败", msg, detail)
            if hasattr(self, "_save_state"):
                self._save_state()
            return {"status": "error", "reason": "place_failed", "action": "UPDATE_TP", "detail": detail}

        if getattr(self, "current_trade_id", None) and hasattr(self, "on_trade_update_targets"):
            try:
                self.on_trade_update_targets(
                    self.current_trade_id,
                    tv_tps=list(self.tv_tps),
                    regime=getattr(self, "regime", None),
                    atr=getattr(self, "current_atr", None),
                )
            except Exception as exc:
                logger.warning("UPDATE_TP trade target update failed: %s", exc)

        if hasattr(self, "_save_state"):
            self._save_state()

        msg = (
            f"动能止盈升级成功 {side} | "
            f"{old_tps} → {new_tps} | 撤 {cancelled} 挂 {placed}"
        )
        self._log("UPDATE_TP", msg, detail)
        self._alert(
            "info",
            "UPDATE_TP",
            f"{theme['accent']} 动能止盈升级 · {theme['label']}",
            msg,
            detail,
        )
        return {"status": "ok", "action": "UPDATE_TP", "detail": detail}

    def _mark_adverse_tier_consumed(self, tier_pct: float) -> None:
        t = round(float(tier_pct), 4)
        if t not in self._adverse_consumed_set():
            self.adverse_consumed_tiers.append(t)
        self.adverse_sl_armed = True

    def _regime_radar_activation(self) -> float:
        from app.core.radar_trail import REGIME_RADAR

        regime = int(getattr(self, "regime", 3) or 3)
        settings = getattr(self, "regime_settings", None) or {}
        row = settings.get(regime) or settings.get(str(regime)) or {}
        if isinstance(row, dict) and row.get("activation") is not None:
            try:
                return float(row["activation"])
            except (TypeError, ValueError):
                pass
        return float(REGIME_RADAR.get(regime, REGIME_RADAR[3])["activation"])

    def _radar_activation_reached(self, curr_px: float) -> bool:
        """Breathing stop is always active from open when monitoring with entry/ATR."""
        self._init_adverse_radar_fields()
        if not getattr(self, "monitoring", False):
            return False
        entry = float(getattr(self, "watched_entry", 0) or 0)
        atr = float(
            getattr(self, "initial_atr", 0)
            or getattr(self, "current_atr", 0)
            or 0
        )
        return entry > 0 and atr > 0

    def _remaining_qty_pct_from_consumed(self, consumed: list | None = None) -> float:
        levels = {int(x) for x in (consumed if consumed is not None else getattr(self, "consumed_tp_levels", None) or [])}
        if {1, 2, 3}.issubset(levels):
            return 0.0
        if {1, 2}.issubset(levels):
            return 0.4
        if 1 in levels:
            return 0.7
        return 1.0

    def _arm_temp_tv_stop_on_open(self, entry: float) -> dict[str, Any]:
        """Hang immediate post-fill hard stop from TV stop_loss × 1.2 (permanent until flat)."""
        self._init_adverse_radar_fields()
        side = str(getattr(self, "current_side", "") or "").upper()
        tv_sl = float(self._pine_stop_loss_ref() or 0)
        temp = compute_temp_tv_stop(entry, side, tv_sl)
        source = "tv_hard_stop"
        if temp <= 0:
            # Fallback: TV atr-based stop if stop_loss missing
            tv_atr = float(getattr(self, "_tv_atr_ref", 0) or 0)
            sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
            if tv_atr > 0 and side in ("LONG", "SHORT"):
                temp = compute_initial_stop(float(entry or 0), side, tv_atr, symbol=sym)
                source = "tv_atr_hard_fallback"
        if temp <= 0:
            return {"ok": False, "reason": "hard_stop_unavailable", "stop_price": 0.0}
        # Hard floor is frozen here — radar uses current_sl / initial_stop separately
        self._frozen_hard_stop_px = float(temp)
        self._tv_hard_sl_price = float(temp)
        self.tv_sl = float(temp) if float(getattr(self, "tv_sl", 0) or 0) <= 0 else float(self.tv_sl)
        self._temp_tv_stop_active = True
        self.atr_scenario = ATR_SCENARIO_PENDING
        self.tp3_limit_active = False
        self._vps_hard_sl_meta = {
            "source": source,
            "stop_price": float(temp),
            "entry": float(entry or 0),
            "side": side,
            "tv_stop_loss": tv_sl,
            "buffer": 1.2,
            "frozen": True,
        }
        return {"ok": True, "stop_price": float(temp), "source": source, "tv_stop_loss": tv_sl}

    def _resolve_and_apply_open_atr_scenario(self, entry: float) -> dict[str, Any]:
        """After hard stop + TP1/TP2: pick scenario 1 (VPS ATR) or 2 (TV atr + TP3).

        Never rewrites frozen hard stop price — only arms radar initial_stop/current_sl.
        """
        self._init_adverse_radar_fields()
        tv_atr = float(getattr(self, "_tv_atr_ref", 0) or 0)
        client = getattr(self, "client", None)
        sym = (
            getattr(self, "canonical_symbol", None)
            or getattr(self, "symbol", None)
            or "ETHUSDT"
        )
        decision = resolve_open_atr(client=client, symbol=sym, tv_atr=tv_atr)
        scenario = str(decision.get("scenario") or ATR_SCENARIO_TV)
        atr_v = float(decision.get("initial_atr") or 0)
        if atr_v <= 0 and tv_atr > 0:
            atr_v = tv_atr
            scenario = ATR_SCENARIO_TV
            decision["tp3_limit_active"] = True
            decision["atr_source"] = "tv_webhook"
        if atr_v <= 0:
            return {"ok": False, "reason": "no_atr_for_breath", **decision}

        frozen = self._frozen_hard_px()
        # Clear lock so init can set the chosen atr once (radar track only)
        self.initial_atr = 0.0
        self._init_breathing_on_open(entry, atr=atr_v)
        # Restore frozen hard — breathing init must not steal hard price
        if frozen > 0:
            self._frozen_hard_stop_px = frozen
            self._tv_hard_sl_price = frozen
        self.atr_scenario = scenario
        self.tp3_limit_active = bool(decision.get("tp3_limit_active"))
        self._temp_tv_stop_active = False
        atr_src = str(decision.get("atr_source") or "")
        meta = dict(getattr(self, "_vps_hard_sl_meta", None) or {})
        meta["atr_source"] = atr_src
        meta["atr_scenario"] = scenario
        meta["tp3_limit_active"] = self.tp3_limit_active
        meta["frozen_hard"] = float(self._frozen_hard_px() or 0)
        self._vps_hard_sl_meta = meta

        detail = {
            "ok": True,
            "scenario": scenario,
            "initial_atr": float(getattr(self, "initial_atr", 0) or 0),
            "initial_stop": float(getattr(self, "initial_stop", 0) or 0),
            "radar_sl": float(getattr(self, "current_sl", 0) or 0),
            "frozen_hard": float(self._frozen_hard_px() or 0),
            "atr_1h": float(decision.get("atr_1h") or 0),
            "tv_atr": tv_atr,
            "tp3_limit_active": self.tp3_limit_active,
            "atr_source": atr_src,
        }
        if hasattr(self, "_log"):
            self._log(
                "ATR_SCENARIO",
                (
                    "场景一·VPS真实ATR武装雷达（硬止损永冻）"
                    if scenario == ATR_SCENARIO_VPS
                    else "场景二·TV理论ATR武装雷达+TP3兜底（硬止损永冻）"
                ),
                detail,
            )
        if scenario == ATR_SCENARIO_TV and hasattr(self, "_alert"):
            self._alert(
                "info",
                "ATR_SCENARIO",
                "本次VPS真实ATR获取失败·已用TV理论ATR继续",
                "TP3已按TV价位挂出兜底（记录通知，非告警）",
                detail,
            )
        return detail

    def _init_breathing_on_open(
        self,
        entry: float,
        atr: float | None = None,
        adx: float | None = None,
        breathing_coefficient: float | None = None,
    ) -> dict:
        """Initialize breathing-stop state at position open.

        ``atr`` is VPS 1h (scenario 1) or TV webhook atr (scenario 2).
        Breathing coefficient seeded from Binance 1h ATR when available.
        """
        self._init_adverse_radar_fields()
        side = getattr(self, "current_side", None) or ""
        atr_v = float(atr or 0) or float(getattr(self, "_tv_atr_ref", 0) or 0)
        if atr_v <= 0:
            atr_v = float(getattr(self, "initial_atr", 0) or getattr(self, "current_atr", 0) or 0)
        atr_v = resolve_atr(atr_v) if atr_v > 0 else resolve_atr(None)

        self.initial_atr = atr_v
        self.current_atr = atr_v
        # Seed 1h breathing coefficient
        try:
            refresh_supervisor_breath(self, force=True)
        except Exception as exc:
            logger.warning("1h breath seed failed: %s", exc)
        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        coef = resolve_breathing_coef(
            breathing_coefficient
            if breathing_coefficient is not None
            else getattr(self, "breathing_coefficient", None),
            sym,
        )
        self.breathing_coefficient = coef

        st = init_breathing_state(
            float(entry or 0),
            str(side),
            atr=atr_v,
            breathing_coefficient=coef,
            symbol=sym,
        )
        self.initial_atr = float(st["initial_atr"])
        self.initial_stop = float(st["initial_stop"])
        self.current_sl = float(st["current_sl"])
        self._tv_hard_sl_price = float(st["current_sl"])
        self.best_price = float(st["best_price"])
        self.breakeven_phase = bool(st["breakeven_phase"])
        self.radar_step_count = int(st.get("step_count") or 0)
        self.remaining_qty_pct = float(st["remaining_qty_pct"])
        self.current_atr = float(st["initial_atr"])
        if adx is not None:
            self.current_adx = resolve_adx(adx)
        hang = apply_stop_order_buffer(side, float(st["initial_stop"]), sym)
        atr_source = "vps_1h" if str(getattr(self, "atr_scenario", "")) == ATR_SCENARIO_VPS else (
            "tv_webhook" if float(getattr(self, "_tv_atr_ref", 0) or 0) > 0 else "fallback"
        )
        self._vps_hard_sl_meta = {
            "source": "breathing_initial",
            "stop_price": float(st["initial_stop"]),
            "hang_stop": float(hang or 0),
            "entry": float(st["entry_price"]),
            "side": side,
            "atr": float(st["initial_atr"]),
            "atr_source": atr_source,
            "atr_scenario": str(getattr(self, "atr_scenario", "") or ""),
            "breathing_coefficient": coef,
            "symbol": sym,
        }
        self._last_breath_trail_alert_sl = 0.0
        return st

    def _process_breathing_stop_tick(self, live_qty: float, curr_px: float) -> bool:
        """Evaluate breathing stop one tick; place/improve SL; close on hit."""
        pause_until = float(getattr(self, "_breath_resize_pause_until", 0) or 0)
        if pause_until and time.time() < pause_until:
            return False
        self._init_adverse_radar_fields()
        # Scenario 2: keep retrying VPS 1h ATR → upgrade + cancel TP3
        try:
            maybe_retry_vps_atr_on_tick(self, live_qty=float(live_qty or 0))
        except Exception:
            pass
        # Soft-refresh 1h ATR → breathing coefficient
        try:
            refresh_supervisor_breath(self, force=False)
        except Exception:
            pass
        entry = float(getattr(self, "watched_entry", 0) or 0)
        side = getattr(self, "current_side", None)
        atr = float(
            getattr(self, "initial_atr", 0)
            or getattr(self, "current_atr", 0)
            or 0
        )
        initial_stop = float(getattr(self, "initial_stop", 0) or 0)
        current_sl = float(getattr(self, "current_sl", 0) or 0)
        best = float(getattr(self, "best_price", 0) or entry or 0)
        phase = bool(getattr(self, "breakeven_phase", False))
        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        coef = resolve_breathing_coef(getattr(self, "breathing_coefficient", None), sym)
        px = float(curr_px or 0)
        if entry <= 0 or atr <= 0 or side not in ("LONG", "SHORT") or px <= 0:
            return False

        if initial_stop <= 0:
            initial_stop = compute_initial_stop(entry, side, atr, symbol=sym)
            self.initial_stop = initial_stop
        if current_sl <= 0:
            current_sl = initial_stop
            self.current_sl = current_sl
            # Dual track: do NOT overwrite frozen hard with radar seed

        was_phase = phase
        tick = apply_breathing_tick(
            side=side,
            price=px,
            entry_price=entry,
            initial_atr=atr,
            initial_stop=initial_stop,
            current_stop=current_sl,
            best_price=best,
            breakeven_phase=phase,
            breathing_coefficient=coef,
            symbol=sym,
        )
        new_sl = float(tick.get("current_sl") or 0)
        new_best = float(tick.get("best_price") or best)
        new_phase = bool(tick.get("breakeven_phase"))
        improved = bool(tick.get("improved"))
        event = str(tick.get("event") or "none")
        step_count = int(tick.get("step_count") or 0)

        self.best_price = new_best
        self.breakeven_phase = new_phase
        self.breathing_coefficient = float(tick.get("breathing_coefficient") or coef)
        if step_count > int(getattr(self, "radar_step_count", 0) or 0):
            self.radar_step_count = step_count
        if improved and new_sl > 0:
            self.current_sl = new_sl
            if not self._uses_dual_stop_track():
                self._tv_hard_sl_price = new_sl
            else:
                # Radar may only tighten vs frozen hard
                self.current_sl = self._clamp_radar_sl_to_tv_floor(new_sl)

        if stop_hit(side, px, float(getattr(self, "current_sl", 0) or 0)):
            consumed = list(getattr(self, "consumed_tp_levels", None) or [])
            rem = float(getattr(self, "remaining_qty_pct", 1.0) or 1.0)
            after_tp = bool(consumed) or rem < 0.999
            if bool(getattr(self, "breakeven_phase", False)) or was_phase:
                phase_label = "追踪止损平仓（阶段二）"
            elif after_tp:
                phase_label = "保本止损平仓（阶段一·TP后）"
            else:
                phase_label = "初始止损平仓（阶段一）"
            if hasattr(self, "_close_all"):
                try:
                    self._close_all(
                        phase_label,
                        close_action="CLOSE_BREATH_STOP",
                        close_trigger="breathing_stop_hit",
                    )
                except Exception as exc:
                    logger.error(
                        "[User %s] CLOSE_BREATH_STOP failed: %s",
                        getattr(self, "user_id", "?"),
                        exc,
                    )
            return True

        live_qty = self._resolve_adverse_live_qty(live_qty)
        if live_qty <= 0 or float(getattr(self, "current_sl", 0) or 0) <= 0:
            return False

        sl_px = float(self.current_sl)
        hang_px = self._exchange_hang_stop_px(sl_px)
        placed = False
        # Heartbeat: touch exchange when price improved OR stop missing OR duplicates.
        need_sync = bool(improved)
        live_stop_n = 0
        if hasattr(self, "_count_live_stop_orders"):
            try:
                live_stop_n = int(self._count_live_stop_orders())
            except Exception:
                live_stop_n = -1
        if live_stop_n < 0:
            # Book unknown — do not place; attempt cancel-only sync refuse path
            logger.warning(
                "[User %s] breath tick: stop book unknown — skip place",
                getattr(self, "user_id", "?"),
            )
            return False
        if live_stop_n > ADVERSE_MAX_STOP_ORDERS:
            need_sync = True  # purge duplicates even if one is "near"
        if not need_sync:
            near = False
            if hasattr(self, "_has_stop_sl_near"):
                try:
                    near = self._has_stop_sl_near(hang_px)
                except Exception:
                    near = None
            if near is None:
                logger.warning(
                    "[User %s] breath tick: stop-near unknown — skip place",
                    getattr(self, "user_id", "?"),
                )
                return False
            need_sync = not near
        if need_sync:
            if self._uses_dual_stop_track() and hasattr(self, "_ensure_radar_sl"):
                # Dual: only move radar; hard price stays frozen (qty repair via separate path)
                if getattr(self, "exchange_id", "") == "deepcoin":
                    placed = bool(self._ensure_radar_sl(live_qty, hang_px))
                else:
                    placed = bool(self._ensure_radar_sl(hang_px, live_qty))
                # Repair missing hard without price change
                if float(self._frozen_hard_px() or 0) > 0 and not self._hard_stop_on_book(self._frozen_hard_px()):
                    try:
                        self._sync_hard_stop_only(live_qty, force_replace=False)
                    except Exception:
                        pass
            elif hasattr(self, "_sync_binance_merged_stop"):
                merged = self._sync_binance_merged_stop(
                    live_qty,
                    radar_sl=sl_px,
                    force_replace=bool(improved or live_stop_n > ADVERSE_MAX_STOP_ORDERS),
                ) or {}
                placed = bool(merged.get("placed") or 0)
            elif hasattr(self, "_sync_tv_hard_stop"):
                merged = self._sync_tv_hard_stop(live_qty, force_replace=improved) or {}
                placed = bool(merged.get("placed") or 0)
            elif hasattr(self, "_ensure_radar_sl"):
                if getattr(self, "exchange_id", "") == "deepcoin":
                    placed = bool(self._ensure_radar_sl(live_qty, hang_px))
                else:
                    placed = bool(self._ensure_radar_sl(hang_px, live_qty))

        meta = dict(tick.get("meta") or {})
        trail_dist_atr = meta.get("trail_dist_atr")
        alert_map = {
            "step": ("BREATH_STEP", "呼吸止损·步进上移"),
            "floor_tp1": ("BREATH_FLOOR", "呼吸止损·TP1底限"),
            "floor_tp2": ("BREATH_FLOOR", "呼吸止损·TP2底限"),
            "phase2_enter": ("BREATH_PHASE2", "呼吸止损·阶段切换"),
            "trail": ("BREATH_TRAIL", "呼吸止损·自适应追踪"),
        }
        should_alert = event in alert_map and (
            event != "trail" or (improved and abs(sl_px - float(getattr(self, "_last_breath_trail_alert_sl", 0) or 0)) > 1e-9)
        )
        if should_alert and (improved or placed or event == "phase2_enter"):
            atype, title = alert_map[event]
            detail = {
                "event": event,
                "current_sl": sl_px,
                "hang_sl": hang_px,
                "new_sl": sl_px,
                "initial_stop": initial_stop,
                "initial_atr": atr,
                "breathing_coefficient": coef,
                "atr_1h": float(getattr(self, "atr_1h", 0) or 0),
                "smooth_ratio": float(getattr(self, "breath_smooth_ratio", 0) or 0),
                "atr_scenario": str(getattr(self, "atr_scenario", "") or ""),
                "tp3_limit_active": bool(getattr(self, "tp3_limit_active", False)),
                "breakeven_phase": new_phase,
                "best_price": new_best,
                "curr_px": px,
                "entry": entry,
                "switch_price": px if event == "phase2_enter" else None,
                "trail_dist_atr": trail_dist_atr,
                "trail_distance": (
                    float(trail_dist_atr) * atr
                    if trail_dist_atr is not None else meta.get("trail_distance")
                ),
                "improved": improved,
                "placed": placed,
                "meta": meta,
            }
            if hasattr(self, "_log"):
                self._log(atype, f"{title} @{sl_px:.2f}", detail)
            if hasattr(self, "_alert"):
                if event == "phase2_enter":
                    msg = (
                        f"切换价{px:.2f} | 呼吸系数={coef:.2f} | "
                        f"追踪距离={float(detail.get('trail_distance') or 0):.2f} "
                        f"| SL@{sl_px:.2f} (挂{hang_px:.2f})"
                    )
                else:
                    msg = (
                        f"SL@{sl_px:.2f} (挂{hang_px:.2f}) | 现价{px:.2f} | "
                        f"呼吸系数={coef:.2f} | phase={'2' if new_phase else '1'}"
                    )
                self._alert("info", atype, title, msg, detail)
            if event == "trail":
                self._last_breath_trail_alert_sl = sl_px

        if improved or placed:
            self.radar_latched = True
            self.radar_activated = True
            if hasattr(self, "_save_state"):
                self._save_state()
        return bool(improved)

    def _refresh_breathing_state_on_recover(self, curr_px: float, entry: float) -> None:
        """Restart: restore breathing SL from persisted state + one tick at mark.

        Never retreats stop. initial_atr stays frozen; 1h ATR refreshes coefficient.
        """
        if curr_px <= 0 or not entry:
            return
        self._init_adverse_radar_fields()
        try:
            refresh_supervisor_breath(self, force=False)
        except Exception:
            pass
        side = getattr(self, "current_side", None)
        atr = float(
            getattr(self, "initial_atr", 0)
            or getattr(self, "current_atr", 0)
            or 0
        )
        if atr <= 0:
            atr = resolve_atr(None)
            self.initial_atr = atr
        elif float(getattr(self, "initial_atr", 0) or 0) <= 0:
            self.initial_atr = atr

        initial_stop = float(getattr(self, "initial_stop", 0) or 0)
        if initial_stop <= 0 and side in ("LONG", "SHORT"):
            sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
            initial_stop = compute_initial_stop(float(entry), str(side), atr, symbol=sym)
            self.initial_stop = initial_stop

        if float(getattr(self, "best_price", 0) or 0) <= 0:
            self.best_price = float(entry)
        if side == "LONG":
            self.best_price = max(float(self.best_price), float(curr_px))
        elif side == "SHORT":
            bp = float(self.best_price)
            self.best_price = min(bp, float(curr_px)) if bp > 0 else float(curr_px)

        current_sl = float(getattr(self, "current_sl", 0) or 0)
        if current_sl <= 0:
            current_sl = float(initial_stop or 0)
            self.current_sl = current_sl

        if side not in ("LONG", "SHORT") or initial_stop <= 0:
            return

        sym = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        coef = resolve_breathing_coef(getattr(self, "breathing_coefficient", None), sym)
        tick = apply_breathing_tick(
            side=side,
            price=float(curr_px),
            entry_price=float(entry),
            initial_atr=atr,
            initial_stop=initial_stop,
            current_stop=current_sl,
            best_price=float(self.best_price),
            breakeven_phase=bool(getattr(self, "breakeven_phase", False)),
            breathing_coefficient=coef,
            symbol=sym,
        )
        new_sl = float(tick.get("current_sl") or current_sl)
        self.best_price = float(tick.get("best_price") or self.best_price)
        self.breakeven_phase = bool(tick.get("breakeven_phase"))
        self.breathing_coefficient = float(tick.get("breathing_coefficient") or coef)
        if new_sl > 0:
            # Only improve (never retreat) relative to persisted current_sl
            if side == "LONG":
                self.current_sl = max(current_sl, new_sl) if current_sl > 0 else new_sl
            else:
                self.current_sl = min(current_sl, new_sl) if current_sl > 0 else new_sl
            self._tv_hard_sl_price = float(self.current_sl)
        self.radar_latched = True
        self.radar_activated = True
        self.remaining_qty_pct = self._remaining_qty_pct_from_consumed(
            getattr(self, "consumed_tp_levels", None)
        )
        logger.info(
            "%s [User %s] 呼吸止损重启恢复: phase=%s best=%.2f SL=%.2f atr=%.4f coef=%.2f",
            self._symbol_tag(),
            getattr(self, "user_id", "?"),
            "2" if self.breakeven_phase else "1",
            float(self.best_price),
            float(self.current_sl or 0),
            atr,
            resolve_breathing_coef(getattr(self, "breathing_coefficient", None), sym),
        )

    def _tp1_limit_still_live_on_book(self) -> bool:
        """Exchange-first: open TP1 limit still present (slice accounting only; not an arm gate)."""
        tps = list(getattr(self, "tv_tps", []) or [])
        if not tps:
            return False
        tp1 = float(tps[0] or 0)
        if tp1 <= 0:
            return False
        from app.core.tp_slice_guard import tp_limit_still_on_book
        prices: list[float] = []
        if hasattr(self, "_open_tp_prices_on_book"):
            prices = list(self._open_tp_prices_on_book() or [])
        elif hasattr(self, "_collect_tp_limit_orders"):
            for o in self._collect_tp_limit_orders() or []:
                try:
                    px = float(o.get("price") or o.get("px") or 0)
                except (TypeError, ValueError):
                    px = 0.0
                if px > 0:
                    prices.append(px)
        return tp_limit_still_on_book(tp1, prices)

    def _has_live_adverse_shield(self) -> bool:
        """Exchange-first: any 10% hard stop still on book or marked armed."""
        self._init_adverse_radar_fields()
        if self._collect_adverse_stop_orders():
            return True
        return bool(self.adverse_sl_armed or self.adverse_sl_prices)

    def _should_disarm_adverse_for_recovery(self, curr_px: float) -> bool:
        """Route A: TV 底线与雷达共存，不因雷达激活撤销 TV 止损。"""
        return False

    def _disarm_shield_before_radar(
        self,
        curr_px: float,
        *,
        reason: str = "radar_path_activation",
        notify: bool = False,
    ) -> dict[str, Any]:
        """Route A: 不撤 TV 硬止损；Binance 由合并单槽表达双层语义。"""
        return {"cancelled": 0, "skipped": "route_a_coexist", "reason": reason}

    def _handoff_shield_to_radar(self, live_qty: float, curr_px: float) -> bool:
        """Ensure breathing stop is evaluated and placed (compat name for startup)."""
        if curr_px <= 0:
            return False
        if not self._radar_activation_reached(curr_px):
            return False
        live_qty = self._resolve_adverse_live_qty(live_qty)
        entry = float(getattr(self, "watched_entry", 0) or 0)
        if hasattr(self, "_refresh_breathing_state_on_recover"):
            self._refresh_breathing_state_on_recover(curr_px, entry)
        elif hasattr(self, "_refresh_radar_state_on_recover"):
            self._refresh_radar_state_on_recover(curr_px, entry)

        placed = False
        if hasattr(self, "_process_radar_trailing"):
            placed = bool(self._process_radar_trailing(live_qty, curr_px))

        sl_px = float(getattr(self, "current_sl", 0) or 0)
        on_book = (
            hasattr(self, "_has_stop_sl_near") and sl_px > 0 and self._has_stop_sl_near(sl_px)
        ) or (
            hasattr(self, "_has_trigger_sl_near") and sl_px > 0
            and self._has_trigger_sl_near(sl_px)
        )
        if not on_book and sl_px > 0 and hasattr(self, "_ensure_radar_sl"):
            if getattr(self, "exchange_id", "") == "deepcoin":
                placed = bool(self._ensure_radar_sl(live_qty, sl_px)) or placed
            else:
                placed = bool(self._ensure_radar_sl(sl_px, live_qty)) or placed

        if sl_px > 0 and hasattr(self, "_has_stop_sl_near"):
            if self._has_stop_sl_near(sl_px):
                self._latch_radar()
            return bool(self._has_stop_sl_near(sl_px))
        if sl_px > 0 and hasattr(self, "_has_trigger_sl_near"):
            if self._has_trigger_sl_near(sl_px):
                self._latch_radar()
            return bool(self._has_trigger_sl_near(sl_px))
        if placed:
            self._latch_radar()
        return placed

    def _classify_tp_reduction(
        self, old_qty: float, new_qty: float, curr_px: float | None = None,
    ) -> str | None:
        if new_qty <= 0 or new_qty >= old_qty - self._qty_match_tol(old_qty, new_qty):
            return None
        if hasattr(self, "_classify_qty_change"):
            cause = self._classify_qty_change(old_qty, new_qty, curr_px=curr_px)
            if cause.startswith("tp"):
                return cause
            return None
        # Deepcoin / fallback: regime ratio slices
        ratios = self.regime_settings[self.regime]["ratios"]
        if hasattr(self, "_calculate_tp_quantities"):
            q1, q2, q3 = self._calculate_tp_quantities(old_qty, ratios)
            slices = [(1, q1), (2, q2), (3, q3)]
        elif hasattr(self, "_split_tp_quantities"):
            q1, q2, q3 = self._split_tp_quantities(old_qty, ratios)
            slices = [(1, q1), (2, q2), (3, q3)]
        else:
            return None
        reduced = old_qty - new_qty
        tol = self._qty_match_tol(old_qty, new_qty)
        for level, slice_qty in slices:
            if slice_qty > 0 and abs(reduced - slice_qty) <= tol:
                consumed = getattr(self, "consumed_tp_levels", None)
                if consumed is not None and level not in consumed:
                    consumed.append(level)
                return f"tp{level}_filled"
        return None

    def _classify_reduction_cause(
        self, old_qty: float, new_qty: float, curr_px: float | None = None,
    ) -> str:
        if new_qty <= 0:
            return "full_close"
        if new_qty > old_qty + self._qty_match_tol(old_qty, new_qty):
            return "manual_add"
        if abs(new_qty - old_qty) <= self._qty_match_tol(old_qty, new_qty):
            return "unchanged"

        tp_cause = self._classify_tp_reduction(old_qty, new_qty, curr_px=curr_px)
        if tp_cause:
            return tp_cause

        if self.adverse_sl_armed or self.adverse_consumed_tiers:
            tier = match_adverse_tier_fill(
                float(self.watched_entry or 0),
                str(self.current_side or "LONG"),
                float(old_qty),
                float(old_qty - new_qty),
                round_qty_fn=self._adverse_round_qty,
                qty_tol=self._qty_match_tol(old_qty, new_qty),
            )
            if tier is not None:
                return f"adverse_sl_{int(round(tier * 100))}pct"

        if hasattr(self, "_classify_qty_change"):
            return self._classify_qty_change(old_qty, new_qty, curr_px=curr_px)
        return "manual_reduce"

    def _adverse_close_side(self) -> str:
        if getattr(self, "exchange_id", "") == "deepcoin":
            return "sell" if self.current_side == "LONG" else "buy"
        return self._close_order_side()

    def _hard_sl_limit_price(self, stop_price: float) -> float:
        return compute_hard_sl_limit_price(
            stop_price, getattr(self, "current_side", None),
        )

    def _is_hard_sl_limit_order(self, o: dict) -> bool:
        """True when open LIMIT is the VPS hard-SL resting reduce-only order."""
        if str(o.get("type") or "").upper() != "LIMIT":
            return False
        if not _order_is_reduce_only(o):
            return False
        px = _order_limit_price(o)
        if px <= 0:
            return False
        tiers = self._shield_tier_prices()
        if not tiers:
            hard = self._exchange_stop_px()
            if hard <= 0:
                return False
            tiers = {round(hard, 2)}
        return any(abs(px - t) <= ADVERSE_STOP_TOLERANCE for t in tiers)

    def _place_adverse_stop_slice(self, stop_price: float, qty: float) -> bool:
        """
        Place VPS hard stop — must be conditional; never a plain LIMIT.

        Single-writer / anti-duplicate:
        - If a stop already exists near this trigger, do NOT place another.
        - If >1 stops exist, cancel-all first; only place when book is empty.
        """
        symbol = getattr(self, "symbol", None)
        client = self.client
        self._last_hard_sl_order_style = None

        # --- hard anti-duplicate gate FIRST (fail-closed before any place path) ---
        try:
            live_n = self._count_live_stop_orders()
        except Exception:
            live_n = -1
        if live_n < 0:
            logger.error(
                "[User %s] %s refuse place stop @%.2f — stop book fetch failed (fail-closed)",
                getattr(self, "user_id", "?"),
                getattr(self, "canonical_symbol", symbol),
                float(stop_price or 0),
            )
            self._last_hard_sl_order_style = "refused_book_unknown"
            return False
        # Dual track: allow place when only radar is live; refuse at max (2)
        if self._uses_dual_stop_track():
            if live_n >= ADVERSE_MAX_STOP_ORDERS:
                # Already at hard+radar — treat as success if hard near target
                if self._hard_stop_on_book(float(stop_price or 0)):
                    self._last_hard_sl_order_style = "skipped_already_live"
                    return True
                logger.info(
                    "[User %s] %s skip place hard @%.2f — book full (%s)",
                    getattr(self, "user_id", "?"),
                    getattr(self, "canonical_symbol", symbol),
                    float(stop_price or 0),
                    live_n,
                )
                self._last_hard_sl_order_style = "skipped_book_full"
                return False
            if live_n >= 1 and self._hard_stop_on_book(float(stop_price or 0)):
                self._last_hard_sl_order_style = "skipped_already_live"
                return True
        elif live_n >= 1:
            logger.info(
                "[User %s] %s skip place stop @%.2f — already %s live (anti-dup)",
                getattr(self, "user_id", "?"),
                getattr(self, "canonical_symbol", symbol),
                float(stop_price or 0),
                live_n,
            )
            self._last_hard_sl_order_style = "skipped_already_live"
            return True

        close_side = self._adverse_close_side()

        if getattr(self, "exchange_id", "") == "deepcoin":
            pos_side = "long" if self.current_side == "LONG" else "short"
            sz = int(self._safe_qty(qty))
            if sz <= 0:
                return False
            trigger_px = round_price(stop_price)
            order = None
            if hasattr(client, "place_trigger_order"):
                try:
                    order = client.place_trigger_order(
                        symbol, close_side, pos_side, sz, trigger_px,
                        order_type="limit",
                        price=self._hard_sl_limit_price(stop_price),
                        td_mode="cross", mrg_position="merge",
                    )
                except TypeError:
                    order = None
                if not order:
                    order = client.place_trigger_order(
                        symbol, close_side, pos_side, sz, trigger_px,
                        order_type="market", td_mode="cross", mrg_position="merge",
                    )
                    if order:
                        self._last_hard_sl_order_style = "deepcoin_trigger_market"
            if order:
                if not self._last_hard_sl_order_style:
                    self._last_hard_sl_order_style = "deepcoin_trigger_limit"
                return True
            return False

        limit_px = self._hard_sl_limit_price(stop_price)
        qty_f = float(qty or 0)

        def _track_algo(order: dict | None) -> None:
            if not order:
                return
            aid = order.get("algoId") or order.get("orderId")
            if not aid:
                return
            pending = list(getattr(self, "_pending_adverse_algo_ids", None) or [])
            aid_int = int(aid)
            if aid_int not in pending:
                pending.append(aid_int)
            self._pending_adverse_algo_ids = pending[-8:]

        # 架构对齐：止损单必须带 quantity，以便 TP1/TP2 后收缩至 70%/40%
        if hasattr(client, "place_stop_market_order") and qty_f > 0:
            order = client.place_stop_market_order(
                close_side, stop_price, symbol, quantity=qty_f, reduce_only=True,
            )
            if order:
                self._last_hard_sl_order_style = "stop_market_qty"
                _track_algo(order)
                return True

        # Fallback: qty Stop-Limit（closePosition 已禁用）
        if hasattr(client, "place_stop_limit_order") and qty_f > 0:
            order = client.place_stop_limit_order(
                close_side, stop_price, limit_px, symbol,
                quantity=qty_f, reduce_only=True,
            )
            if order:
                self._last_hard_sl_order_style = "stop_limit"
                _track_algo(order)
                logger.warning(
                    "[User %s] 硬止损降级 Stop-Limit qty=%.4f @%.2f",
                    getattr(self, "user_id", "?"),
                    qty_f,
                    float(stop_price or 0),
                )
                return True

        if hasattr(client, "place_stop_market_order"):
            # Last resort: closePosition only if qty unavailable
            order = client.place_stop_market_order(
                close_side, stop_price, symbol, quantity=None,
            )
            if order:
                self._last_hard_sl_order_style = "stop_market_close_all"
                _track_algo(order)
                logger.warning(
                    "[User %s] 硬止损无 qty，降级 closePosition @%.2f",
                    getattr(self, "user_id", "?"),
                    float(stop_price or 0),
                )
                return True
        return False

    def _is_adverse_stop_order(self, o: dict, tier_prices: set[float]) -> bool:
        if not tier_prices:
            return False
        otype = str(o.get("type") or o.get("orderType") or "").upper()
        close_side = str(self._adverse_close_side() or "").upper()
        order_side = str(o.get("side", "")).upper()

        # Resting reduce-only LIMIT at VPS hard SL (基础单硬止损)
        if otype == "LIMIT":
            px = _order_limit_price(o)
            if px <= 0:
                return False
            if not any(abs(px - t) <= ADVERSE_STOP_TOLERANCE for t in tier_prices):
                return False
            if not _order_is_reduce_only(o):
                return False
            if close_side and order_side and order_side != close_side:
                return False
            return True

        stop_px = _order_stop_price(o)
        if stop_px <= 0:
            return False
        if not any(abs(stop_px - t) <= ADVERSE_STOP_TOLERANCE for t in tier_prices):
            return False
        if getattr(self, "exchange_id", "") == "deepcoin":
            return True
        if not _is_stop_market_like(o):
            return False
        if _order_is_close_position(o):
            if close_side and order_side and order_side != close_side:
                return False
        return True

    def _collect_pending_adverse_algo_orders(self, tier_prices: set[float]) -> list[dict]:
        """Fallback when openAlgoOrders lags — query algoId from recent placements."""
        symbol = getattr(self, "symbol", None)
        client = self.client
        if not symbol or not hasattr(client, "get_algo_order"):
            return []
        found: list[dict] = []
        seen: set[int] = set()
        for aid in list(getattr(self, "_pending_adverse_algo_ids", None) or []):
            try:
                aid_int = int(aid)
            except (TypeError, ValueError):
                continue
            if aid_int in seen:
                continue
            seen.add(aid_int)
            o = client.get_algo_order(symbol, aid_int)
            if o and self._is_adverse_stop_order(o, tier_prices):
                found.append(o)
        return found

    def _collect_adverse_stop_orders(self) -> list[dict]:
        orders: list[dict] = []
        symbol = getattr(self, "symbol", None)
        tier_prices = self._shield_tier_prices()

        if getattr(self, "exchange_id", "") == "deepcoin":
            try:
                pending = self.client.get_trigger_orders_pending(symbol) or []
                for o in pending:
                    px = float(o.get("triggerPrice", 0) or 0)
                    if tier_prices and any(abs(px - t) <= ADVERSE_STOP_TOLERANCE for t in tier_prices):
                        orders.append(o)
            except Exception:
                pass
            return orders

        seen_ids: set[str | int] = set()
        for o in self.client.get_open_orders(symbol) or []:
            if self._is_adverse_stop_order(o, tier_prices):
                oid = o.get("algoId") or o.get("orderId")
                if oid is not None:
                    seen_ids.add(oid)
                orders.append(o)
        for o in self._collect_pending_adverse_algo_orders(tier_prices):
            oid = o.get("algoId") or o.get("orderId")
            if oid is not None and oid in seen_ids:
                continue
            if oid is not None:
                seen_ids.add(oid)
            orders.append(o)
        return orders

    def _cancel_adverse_stop_orders(self) -> int:
        cancelled = 0
        symbol = getattr(self, "symbol", None)
        orders = self._collect_adverse_stop_orders()
        if not orders:
            return 0

        if getattr(self, "exchange_id", "") == "deepcoin":
            for o in orders:
                oid = o.get("ordId") or o.get("orderId")
                if oid:
                    self.client.cancel_trigger_order(symbol, oid)
                    cancelled += 1
                    time.sleep(0.2)
            return cancelled

        for o in orders:
            oid = o.get("algoId") or o.get("orderId")
            if oid:
                self.client.cancel_order(symbol, int(oid))
                cancelled += 1
                time.sleep(0.2)
        if cancelled:
            self._pending_adverse_algo_ids = []
        return cancelled

    def _purge_excess_adverse_stops(self, plan: list[dict]) -> int:
        """Keep at most one adverse stop per tier price; cancel duplicates."""
        if not plan:
            return 0
        open_stops = self._collect_adverse_stop_orders()
        if len(open_stops) <= len(plan):
            return 0

        wanted: dict[float, float] = {
            round(float(t["stop_price"]), 2): float(t["qty"]) for t in plan
        }
        by_price: dict[float, list[dict]] = {}
        for o in open_stops:
            px = _adverse_defense_price(o)
            if px <= 0:
                continue
            bucket = next(
                (k for k in wanted if abs(px - k) <= ADVERSE_STOP_TOLERANCE),
                None,
            )
            if bucket is None:
                continue
            by_price.setdefault(bucket, []).append(o)

        symbol = getattr(self, "symbol", None)
        cancelled = 0
        qty_tol = self._qty_match_tol(
            float(plan[0].get("qty", 0) or 0) if plan else 0,
            float(plan[-1].get("qty", 0) or 0) if plan else 0,
        )
        for px, orders_at_px in by_price.items():
            if len(orders_at_px) <= 1:
                continue
            target_qty = wanted.get(px, 0)
            orders_at_px.sort(
                key=lambda o: abs(_order_qty_value(o) - target_qty),
            )
            for extra in orders_at_px[1:]:
                oid = extra.get("algoId") or extra.get("orderId") or extra.get("ordId")
                if not oid:
                    continue
                if getattr(self, "exchange_id", "") == "deepcoin":
                    self.client.cancel_trigger_order(symbol, oid)
                else:
                    self.client.cancel_order(symbol, int(oid))
                cancelled += 1
                time.sleep(0.15)
        return cancelled

    def _verify_adverse_tier_prices_present(self, plan: list[dict]) -> int:
        """Count tiers with ≥1 live stop at the correct entry-based trigger price."""
        if not plan:
            return 0
        open_stops = self._collect_adverse_stop_orders()
        matched = 0
        for tier in plan:
            target_px = round(float(tier["stop_price"]), 2)
            for o in open_stops:
                if abs(_adverse_defense_price(o) - target_px) <= ADVERSE_STOP_TOLERANCE:
                    matched += 1
                    break
        return matched

    def _tier_has_live_stop(self, tier: dict[str, Any], open_stops: list[dict]) -> bool:
        target_px = round(float(tier["stop_price"]), 2)
        target_qty = float(tier["qty"])
        qty_tol = self._qty_match_tol(target_qty, target_qty)
        for o in open_stops:
            if abs(_adverse_defense_price(o) - target_px) > ADVERSE_STOP_TOLERANCE:
                continue
            if order_qty_covers_tier(o, target_qty, qty_tol):
                return True
        return False

    def _missing_adverse_tier_slices(self, plan: list[dict]) -> list[dict]:
        """Only tiers with no matching live stop (price + qty) — incremental patch target."""
        if not plan:
            return []
        open_stops = self._collect_adverse_stop_orders()
        return [t for t in plan if not self._tier_has_live_stop(t, open_stops)]

    def _refresh_adverse_shield_audit(
        self,
        plan: list[dict],
        *,
        retries: int = 1,
        delay: float = 0.0,
    ) -> dict[str, Any]:
        """Re-read open orders; retry when book lags after place/cancel."""
        audit = self._audit_adverse_shield_live(plan)
        attempts = max(1, int(retries))
        for _ in range(attempts - 1):
            if audit.get("aligned"):
                break
            if delay > 0:
                time.sleep(delay)
            audit = self._audit_adverse_shield_live(plan)
        return audit

    def _shield_misalign_code(self, audit: dict[str, Any]) -> str | None:
        missing = audit.get("missing_tiers") or []
        if missing:
            level = int(missing[0].get("level", 1))
            return f"tier{level}_missing"
        if audit.get("open_count", 0) > ADVERSE_MAX_STOP_ORDERS:
            return "duplicate_stops"
        expected = int(audit.get("expected") or 0)
        if expected > 0 and int(audit.get("price_present") or 0) < expected:
            return "tier1_missing"
        return None

    def _maybe_alert_shield_misalign(
        self,
        audit: dict[str, Any],
        detail: dict[str, Any],
        *,
        context: str = "repair",
    ) -> None:
        if audit.get("aligned"):
            return
        code = self._shield_misalign_code(audit)
        if not code:
            return
        placed = int(detail.get("placed", 0) or 0)
        if placed <= 0 and not detail.get("force_alert"):
            return
        unit = "张" if getattr(self, "exchange_id", "") == "deepcoin" else "ETH"
        msg = (
            f"已撤旧单 {detail.get('purged_duplicates', 0)} 笔、新挂 {placed} 笔，但核实未通过 | "
            f"实盘 {detail.get('live_qty', '—')} {unit} | {code}"
        )
        payload = {
            **detail,
            "misalign_code": code,
            "audit": audit,
            "context": context,
            "exchange": getattr(self, "exchange_id", "binance"),
            "side": getattr(self, "current_side", None),
            "entry": getattr(self, "watched_entry", 0),
        }
        self._log("ADVERSE_SL_MISALIGN", msg, payload)
        self._alert(
            "critical",
            "ADVERSE_SL_MISALIGN",
            "呼吸止损未对齐",
            msg + " | 系统已退避冷却，下轮自动重试；请勿手动重复挂单",
            payload,
        )

    def _sync_adverse_shield_with_retry(self, live_qty: float) -> dict[str, Any]:
        """Exchange-first shield audit with settle retries (post place/cancel)."""
        live_qty = self._resolve_adverse_live_qty(live_qty)
        plan = self._compute_adverse_stop_plan(live_qty)
        self._refresh_adverse_shield_audit(
            plan,
            retries=ADVERSE_VERIFY_RETRIES,
            delay=ADVERSE_VERIFY_RETRY_DELAY_SEC,
        )
        return self._sync_adverse_shield_from_exchange(live_qty)

    def _audit_adverse_shield_live(self, plan: list[dict]) -> dict[str, Any]:
        open_stops = self._collect_adverse_stop_orders()
        verified_strict = self._verify_adverse_stops(plan)
        price_present = self._verify_adverse_tier_prices_present(plan)
        missing = self._missing_adverse_tier_slices(plan)
        open_count = len(open_stops)
        expected = len(plan)
        aligned = (
            expected > 0
            and price_present >= expected
            and open_count <= ADVERSE_MAX_STOP_ORDERS
            and not missing
        )
        return {
            "verified_strict": verified_strict,
            "price_present": price_present,
            "expected": expected,
            "open_count": open_count,
            "missing_tiers": missing,
            "aligned": aligned,
            "needs_purge_only": (
                expected > 0
                and price_present >= expected
                and open_count > ADVERSE_MAX_STOP_ORDERS
            ),
        }

    def _sync_adverse_shield_from_exchange(self, live_qty: float) -> dict[str, Any]:
        """
        Step 1 in adverse flow: trust exchange book, then align internal records.
        Restart-safe — does not place or cancel orders.
        """
        self._init_adverse_radar_fields()
        live_qty = self._resolve_adverse_live_qty(live_qty)
        plan = self._compute_adverse_stop_plan(live_qty)
        audit = self._audit_adverse_shield_live(plan)
        open_stops = self._collect_adverse_stop_orders()

        if open_stops:
            live_prices = sorted({
                _adverse_defense_price(o) for o in open_stops if _adverse_defense_price(o) > 0
            })
            if live_prices:
                self.adverse_sl_prices = live_prices
                self.adverse_sl_armed = True
                self._pending_adverse_algo_ids = []
        elif audit["aligned"]:
            self.adverse_sl_prices = [float(t["stop_price"]) for t in plan]
            self.adverse_sl_armed = True
        elif not self.adverse_consumed_tiers:
            self.adverse_sl_armed = False
            self.adverse_sl_prices = []

        audit["live_qty"] = live_qty
        audit["plan"] = plan
        audit["synced_armed"] = self.adverse_sl_armed
        return audit

    def _on_adverse_startup_reconcile(self, live_qty: float, curr_px: float) -> dict[str, Any]:
        """Restart: recompute VPS SL, purge stale tight stops, re-arm if needed."""
        self._init_adverse_radar_fields()
        self._adverse_last_repair_ts = time.time()

        entry = float(getattr(self, "watched_entry", 0) or 0)
        side = getattr(self, "current_side", None)
        if live_qty > 0 and entry > 0 and side in ("LONG", "SHORT"):
            from app.core.startup_reconcile import recompute_vps_hard_sl_on_recovery
            recompute_vps_hard_sl_on_recovery(self, entry_px=entry, side=side)

        audit = self._sync_adverse_shield_from_exchange(live_qty)
        plan = audit.get("plan") or []
        expected_px = float(plan[0]["stop_price"]) if plan else 0.0
        open_stops = self._collect_adverse_stop_orders()
        if not open_stops and hasattr(self.client, "get_open_orders"):
            close_side = str(self._adverse_close_side() or "").upper()
            symbol = getattr(self, "symbol", None)
            for o in self.client.get_open_orders(symbol) or []:
                if str(o.get("side", "")).upper() != close_side:
                    continue
                if _is_stop_market_like(o) or _adverse_defense_price(o) > 0:
                    open_stops.append(o)
        live_px = _adverse_defense_price(open_stops[0]) if open_stops else 0.0

        if (
            expected_px > 0
            and live_px > 0
            and abs(live_px - expected_px) > ADVERSE_STOP_TOLERANCE
        ):
            cancelled = 0
            symbol = getattr(self, "symbol", None)
            for o in open_stops:
                oid = o.get("algoId") or o.get("orderId")
                if oid and symbol:
                    self.client.cancel_order(symbol, int(oid))
                    cancelled += 1
                    time.sleep(0.2)
            cancelled += self._cancel_adverse_stop_orders()
            logger.info(
                "[User %s] 重启升级硬止损: 撤旧单 @ %.2f → 新目标 %.2f (撤 %s 笔)",
                self.user_id, live_px, expected_px, cancelled,
            )
            repair = self._arm_adverse_staged_stops(live_qty, 0.0, repair=True)
            audit = {**audit, **repair}
            audit["startup_stale_stop"] = True
            audit["stale_stop_px"] = live_px
            audit["expected_stop_px"] = expected_px
            audit["startup_purged"] = cancelled
            audit["adverse_pct"] = round(self._adverse_move_pct(curr_px) * 100, 2)
            return audit

        purged = 0
        if audit.get("needs_purge_only") and plan:
            purged = self._purge_excess_adverse_stops(plan)
            audit = self._sync_adverse_shield_from_exchange(live_qty)
        audit["startup_purged"] = purged
        audit["adverse_pct"] = round(self._adverse_move_pct(curr_px) * 100, 2)
        if audit.get("aligned"):
            self.adverse_arm_dingtalk_sent = True
            logger.info(
                "[User %s] adverse shield startup: live book aligned (%s/%s tiers), skip re-arm",
                self.user_id, audit.get("price_present"), audit.get("expected"),
            )
        return audit

    def _verify_adverse_stops(self, plan: list[dict]) -> int:
        if not plan:
            return 0
        matched = 0
        open_stops = self._collect_adverse_stop_orders()
        used_ids: set[str | int] = set()
        for tier in plan:
            target_px = round(float(tier["stop_price"]), 2)
            target_qty = float(tier["qty"])
            qty_tol = self._qty_match_tol(target_qty, target_qty)
            for o in open_stops:
                oid = o.get("orderId") or o.get("ordId")
                if oid in used_ids:
                    continue
                stop_px = _adverse_defense_price(o)
                if abs(stop_px - target_px) > ADVERSE_STOP_TOLERANCE:
                    continue
                if not order_qty_covers_tier(o, target_qty, qty_tol):
                    continue
                matched += 1
                if oid is not None:
                    used_ids.add(oid)
                break
        return matched

    def _adverse_stops_need_repair(self, plan: list[dict]) -> bool:
        audit = self._audit_adverse_shield_live(plan)
        if audit["aligned"]:
            return False
        if audit["needs_purge_only"]:
            return True
        return bool(audit["missing_tiers"])

    def _can_repair_adverse_stops(self) -> bool:
        return (time.time() - float(getattr(self, "_adverse_last_repair_ts", 0) or 0)) >= ADVERSE_REPAIR_COOLDOWN_SEC

    def _disarm_adverse_staged_stops(
        self, *, reason: str = "recovery", notify: bool = True,
    ) -> dict[str, Any]:
        open_before = self._collect_adverse_stop_orders()
        if not self.adverse_sl_armed and not self.adverse_consumed_tiers and not open_before:
            return {"cancelled": 0, "reason": reason}

        n = self._cancel_adverse_stop_orders()
        self.adverse_sl_armed = False
        self.adverse_sl_prices = []
        self.adverse_consumed_tiers = []
        self._pending_adverse_algo_ids = []
        self._adverse_last_repair_ts = time.time()
        self.adverse_arm_dingtalk_sent = False

        result = {"cancelled": n, "reason": reason, "had_open": len(open_before)}
        if n > 0:
            logger.info(
                "[User %s] adverse SL disarmed (%s), cancelled %s stops",
                self.user_id, reason, n,
            )
        live_qty = self._resolve_adverse_live_qty(float(getattr(self, "watched_qty", 0) or 0))
        flat_reset = live_qty <= 0 or reason in ("flat_reset", "close_all")
        if notify and (n > 0 or open_before) and not flat_reset:
            entry = float(self.watched_entry or 0)
            stop_px = self._exchange_stop_px()
            label = self._hard_stop_label()
            msg = (
                f"雷达接管 · {reason} | 已撤 {label} {n} 笔"
                + (f" @{stop_px:.2f}" if stop_px > 0 else "")
            )
            self._log("ADVERSE_SL_DISARM", msg, result)
            self._alert(
                "info",
                "ADVERSE_SL_DISARM",
                "旧盾撤销 · 呼吸止损接管",
                msg,
                {**result, "entry": entry, "side": self.current_side, "stop_price": stop_px},
            )
        elif notify and flat_reset and n > 0:
            self._log(
                "ADVERSE_SL_DISARM",
                f"清仓撤盾 · {reason} | 已撤 {n} 笔",
                result,
            )
        if hasattr(self, "_save_state"):
            self._save_state()
        return result

    def _arm_adverse_shield_at_open(self, live_qty: float) -> dict[str, Any]:
        """开仓后挂 TV 硬止损（交易所优先，已存在则跳过）。"""
        return self._arm_adverse_staged_stops(live_qty, 0.0, repair=False, at_open=True)

    def _arm_adverse_staged_stops(
        self, live_qty: float, adverse_pct: float, *, repair: bool = False, at_open: bool = False,
    ) -> dict[str, Any]:
        """
        TV tv_sl hard stop arm sequence (exchange-first):
        1) sync live position + open stops
        2) skip if already aligned
        3) purge duplicates only
        4) place ONLY if missing (never cancel-all + blind re-arm)
        禁止 VPS 10%/宽止损兜底。
        """
        live_qty = self._resolve_adverse_live_qty(live_qty)
        if live_qty <= 0:
            return {"armed": False, "reason": "no_live_position", "live_qty": 0}

        audit = self._sync_adverse_shield_from_exchange(live_qty)
        plan = audit.get("plan") or []
        if not plan:
            if self.adverse_consumed_tiers:
                self.adverse_sl_armed = True
            return {"armed": False, "reason": "all_tiers_consumed", "consumed": list(self.adverse_consumed_tiers)}

        if audit["aligned"]:
            self.adverse_arm_dingtalk_sent = True
            if hasattr(self, "_save_state"):
                self._save_state()
            return {
                "armed": True,
                "placed": 0,
                "verified": audit["verified_strict"],
                "plan": plan,
                "skipped": "live_already_aligned",
                "open_adverse_stops": audit["open_count"],
            }

        purged = 0
        if audit["needs_purge_only"] or audit["open_count"] > ADVERSE_MAX_STOP_ORDERS:
            purged = self._purge_excess_adverse_stops(plan)
            if purged:
                time.sleep(0.35)
                audit = self._sync_adverse_shield_from_exchange(live_qty)
                if audit["aligned"]:
                    self._adverse_last_repair_ts = time.time()
                    return {
                        "armed": True,
                        "placed": 0,
                        "verified": audit["verified_strict"],
                        "plan": plan,
                        "skipped": "purged_duplicates_only",
                        "purged_duplicates": purged,
                    }

        missing = audit.get("missing_tiers") or self._missing_adverse_tier_slices(plan)
        if not missing:
            self._adverse_last_repair_ts = time.time()
            return {
                "armed": self.adverse_sl_armed,
                "placed": 0,
                "verified": audit["verified_strict"],
                "plan": plan,
                "skipped": "no_missing_tiers",
                "purged_duplicates": purged,
            }

        placed = 0
        prices = list(self.adverse_sl_prices or [])
        for tier in missing:
            ok = self._place_adverse_stop_slice(tier["stop_price"], tier["qty"])
            if ok:
                placed += 1
                px = float(tier["stop_price"])
                if px not in prices:
                    prices.append(px)
            time.sleep(0.4)

        purged += self._purge_excess_adverse_stops(plan)
        if placed:
            audit = self._sync_adverse_shield_with_retry(live_qty)
        else:
            audit = self._sync_adverse_shield_from_exchange(live_qty)
        plan = audit.get("plan") or plan
        verified = audit["verified_strict"]
        open_count = audit["open_count"]
        aligned = audit.get("aligned", False)

        self.adverse_sl_armed = audit["synced_armed"] or placed > 0 or bool(self.adverse_consumed_tiers)
        self.adverse_sl_prices = prices or [float(t["stop_price"]) for t in plan]
        self._adverse_last_repair_ts = time.time()

        detail = {
            "adverse_pct": round(adverse_pct * 100, 2) if adverse_pct else 0.0,
            "hard_stop_pct": round(ADVERSE_HARD_STOP_PCT * 100, 1),
            "tv_sl": float(getattr(self, "tv_sl", 0) or 0),
            "shield_label": self._hard_stop_label(),
            "entry": self.watched_entry,
            "side": self.current_side,
            "exchange": getattr(self, "exchange_id", "binance"),
            "live_qty": live_qty,
            "plan": plan,
            "placed": placed,
            "placed_missing_only": placed,
            "missing_before": [t.get("tier_pct") for t in missing],
            "verified": verified,
            "open_adverse_stops": open_count,
            "purged_duplicates": purged,
            "consumed_tiers": list(self.adverse_consumed_tiers),
            "stop_price": plan[0]["stop_price"] if plan else self._exchange_stop_px(),
            "repair": repair,
            "at_open": at_open,
            "synced_from_exchange": True,
            "aligned": aligned,
        }
        if placed > 0 and not aligned:
            self._maybe_alert_shield_misalign(audit, detail, context="arm" if at_open else "repair")
        if placed == 0 and not repair:
            if hasattr(self, "_save_state"):
                self._save_state()
            return {
                "armed": self.adverse_sl_armed,
                "placed": 0,
                "verified": verified,
                "plan": plan,
                "skipped": "no_placement_needed",
                **detail,
            }
        if not repair and placed > 0 and aligned and not self.adverse_arm_dingtalk_sent:
            stop_px = detail["stop_price"]
            label = self._hard_stop_label()
            msg = (
                f"{label} 已挂 | 开仓价 {detail['entry']:.2f} → 止损 @{stop_px:.2f} | "
                f"全平 {detail['live_qty']}"
            )
            self._log("ADVERSE_SL", msg, detail)
            self._alert("warning", "ADVERSE_SL", label, msg, detail)
            self.adverse_arm_dingtalk_sent = True
        elif repair and placed > 0:
            label = self._hard_stop_label()
            msg = f"{label} 补挂 | @{detail['stop_price']:.2f} qty={detail['live_qty']}"
            self._log("ADVERSE_SL_REPAIR", msg, detail)
        if hasattr(self, "_save_state"):
            self._save_state()
        return {
            "armed": self.adverse_sl_armed,
            "placed": placed,
            "verified": verified,
            "aligned": aligned,
            "plan": plan,
            **detail,
        }

    def _repair_adverse_stops_remaining(self, live_qty: float, adverse_pct: float) -> dict[str, Any]:
        return self._arm_adverse_staged_stops(live_qty, adverse_pct, repair=True)

    def _process_adverse_radar_guard(
        self, live_qty: float, curr_px: float, adverse_pct: float | None = None,
    ) -> bool:
        """
        Sentinel: maintain 10% hard stop while radar not active.
        Exchange-first — repair missing only (cooldown-gated).
        """
        self._init_adverse_radar_fields()
        if adverse_pct is None:
            adverse_pct = self._adverse_move_pct(curr_px)

        live_qty = self._resolve_adverse_live_qty(live_qty)
        if live_qty <= 0:
            return False

        progress = (
            self._radar_activation_progress(curr_px)
            if hasattr(self, "_radar_activation_progress")
            else 0.0
        )
        if progress >= 1.0 or self._is_radar_engaged():
            return False

        audit = self._sync_adverse_shield_from_exchange(live_qty)
        if audit.get("aligned"):
            return False

        if not self._can_repair_adverse_stops():
            return False

        repair_mode = audit.get("open_count", 0) > 0
        return bool(
            self._arm_adverse_staged_stops(live_qty, adverse_pct, repair=repair_mode).get("armed")
        )

    def _next_unconsumed_tp_price(self) -> float:
        consumed = set(getattr(self, "consumed_tp_levels", []) or [])
        for i, px in enumerate(getattr(self, "tv_tps", []) or []):
            level = i + 1
            if level not in consumed and float(px or 0) > 0:
                return float(px)
        return 0.0

    def _boost_radar_after_tp_fill(self, change_type: str, curr_px: float, live_qty: float) -> None:
        """TP1/TP2 fill: update remaining pct, then atomically resize stop qty (no price bump).

        Idempotent: each TP level resizes the stop at most once. Re-entry (false
        consumed clear/re-mark, duplicate notify) must NOT cancel↔rehang.
        """
        if change_type not in ("tp1_filled", "tp2_filled", "tp3_filled"):
            return
        consumed = list(getattr(self, "consumed_tp_levels", None) or [])
        level = {"tp1_filled": 1, "tp2_filled": 2, "tp3_filled": 3}.get(change_type)
        if level and level not in consumed:
            consumed.append(level)
            self.consumed_tp_levels = consumed
        self.remaining_qty_pct = self._remaining_qty_pct_from_consumed(consumed)

        done = getattr(self, "_stop_qty_resized_levels", None)
        if done is None:
            self._stop_qty_resized_levels = set()
            done = self._stop_qty_resized_levels
        if level and int(level) in done:
            logger.info(
                "[User %s] skip TP stop resize — already done for TP%s (anti-thrash)",
                getattr(self, "user_id", "?"),
                level,
            )
            if hasattr(self, "_save_state"):
                self._save_state()
            return

        if hasattr(self, "_save_state"):
            self._save_state()

        # Pause breathing price ticks while stop qty is resized (avoid race)
        self._breath_resize_pause_until = time.time() + 8.0

        resize_qty = float(live_qty or 0)
        if resize_qty <= 0 and hasattr(self, "_resolve_adverse_live_qty"):
            resize_qty = float(self._resolve_adverse_live_qty(0) or 0)
        if resize_qty <= 0:
            init_q = float(getattr(self, "initial_qty", 0) or 0)
            resize_qty = init_q * float(self.remaining_qty_pct or 0)

        stop_px = float(getattr(self, "current_sl", 0) or 0)
        if resize_qty > 0 and stop_px > 0 and hasattr(self, "_sync_binance_merged_stop"):
            try:
                # Prefer soft sync first — only force_replace when book stop qty/price wrong.
                already_ok = False
                if hasattr(self, "_has_stop_sl_near"):
                    try:
                        hang = (
                            self._exchange_hang_stop_px(stop_px)
                            if hasattr(self, "_exchange_hang_stop_px")
                            else stop_px
                        )
                        already_ok = bool(self._has_stop_sl_near(hang)) and (
                            self._count_live_stop_orders() <= ADVERSE_MAX_STOP_ORDERS
                        )
                    except Exception:
                        already_ok = False
                if already_ok:
                    logger.info(
                        "[User %s] TP后止损已在簿，跳过撤挂 remaining=%.0f%% | %s",
                        getattr(self, "user_id", "?"),
                        float(self.remaining_qty_pct) * 100.0,
                        change_type,
                    )
                else:
                    self._sync_binance_merged_stop(
                        resize_qty, radar_sl=stop_px, force_replace=True, at_open=False,
                    )
                    logger.info(
                        "[User %s] TP后止损数量收缩 remaining=%.0f%% qty=%.4f @%.2f | %s",
                        getattr(self, "user_id", "?"),
                        float(self.remaining_qty_pct) * 100.0,
                        resize_qty,
                        stop_px,
                        change_type,
                    )
                if level:
                    done.add(int(level))
                    if hasattr(self, "_save_state"):
                        self._save_state()
            except Exception as exc:
                logger.error(
                    "[User %s] TP后止损数量收缩失败: %s",
                    getattr(self, "user_id", "?"),
                    exc,
                )
        elif change_type == "tp3_filled":
            if level:
                done.add(int(level))
            logger.info(
                "[User %s] TP3不挂限价；阶段二由呼吸引擎接管 | remaining=%.2f",
                getattr(self, "user_id", "?"),
                float(self.remaining_qty_pct),
            )

    def _orchestrate_defense_monitoring(self, live_qty: float, curr_px: float) -> None:
        """
        Unified defense: breathing stop (hard+radar merged) + TP12.
        All exchanges share one breathing tick; exchange place APIs differ only.
        """
        if curr_px <= 0:
            return
        # Pause price ticks while TP-fill stop qty resize is in flight
        pause_until = float(getattr(self, "_breath_resize_pause_until", 0) or 0)
        if pause_until and time.time() < pause_until:
            return

        live_qty = self._resolve_adverse_live_qty(live_qty)
        if hasattr(self, "_sync_consumed_tp_levels"):
            self._sync_consumed_tp_levels(live_qty, curr_px)

        if self._radar_activation_reached(curr_px):
            # Breathing tick owns place/improve. Trailing return = stop PRICE improved only.
            if hasattr(self, "_process_radar_trailing"):
                self._process_radar_trailing(live_qty, curr_px)
            elif self._handoff_shield_to_radar(live_qty, curr_px):
                pass
            if self._uses_dual_stop_track():
                # DeepCoin historically dual-slot; mixin forces single-track=False for breathing
                self._process_adverse_radar_guard(live_qty, curr_px)
            # Do NOT second-sync here: a follow-up force_replace on every sentinel
            # poll was the cancel↔rehang loop (~5s). Missing stops are repaired inside
            # _process_breathing_stop_tick when _has_stop_sl_near is false.
            return

        # Missing entry/ATR — keep any mounted stop repaired until breathing can arm
        self._process_adverse_radar_guard(live_qty, curr_px)

    def _orchestrate_qty_change(
        self,
        old_qty: float,
        new_qty: float,
        entry: float,
        curr_px: float,
    ) -> dict[str, Any]:
        """
        Classify reduction cause and apply correct defense response.
        TP fill → realign TP + radar toward TP3
        Adverse SL fill → repair remaining 4/5% tiers only
        """
        cause = self._classify_reduction_cause(old_qty, new_qty, curr_px=curr_px)
        result: dict[str, Any] = {"change_type": cause, "old_qty": old_qty, "new_qty": new_qty}

        # If step-match missed but qty+book says TP filled, reclassify before heal
        if cause == "manual_reduce" and hasattr(self, "_sync_consumed_tp_levels"):
            before = set(int(x) for x in (getattr(self, "consumed_tp_levels", []) or []))
            self._sync_consumed_tp_levels(new_qty, curr_px)
            after = set(int(x) for x in (getattr(self, "consumed_tp_levels", []) or []))
            gained = sorted(after - before)
            if gained:
                cause = f"tp{gained[0]}_filled"
                result["change_type"] = cause
                result["reclassified_from"] = "manual_reduce"

        if cause.startswith("adverse_sl_"):
            tier_key = cause.replace("adverse_sl_", "").replace("pct", "")
            try:
                tier_pct = int(tier_key) / 100.0
            except ValueError:
                tier_pct = ADVERSE_HARD_STOP_PCT
            self._mark_adverse_tier_consumed(tier_pct)
            self.adverse_sl_armed = False
            self.adverse_sl_prices = []
            tp_result = self._smart_realign_defenses(
                new_qty, entry, dynamic_sl=None,
                reason=f"呼吸止损触发 · {cause}",
            )
            result.update({
                "defense": tp_result,
                "action_msg": f"呼吸止损全平 · {cause}",
            })
            self._alert(
                "critical",
                "ADVERSE_SL_HIT",
                "呼吸止损触发",
                f"{cause} 全平 {old_qty}→{new_qty}",
                result,
            )
            return result

        if cause.startswith("tp"):
            self._boost_radar_after_tp_fill(cause, curr_px, new_qty)
            sl_to_pass = self._radar_sl_to_pass() if hasattr(self, "_radar_sl_to_pass") else None
            if self._should_disarm_adverse_for_recovery(curr_px):
                self._disarm_adverse_staged_stops(reason="tp_fill_profit_recovery")
            defense = self._smart_realign_defenses(
                new_qty,
                entry,
                dynamic_sl=sl_to_pass,
                reason=f"止盈吃单 · {cause} · 仅挂剩余TP+雷达（禁止重挂已成交档）",
            )
            if hasattr(self, "_process_radar_trailing"):
                self._process_radar_trailing(new_qty, curr_px)
            elif self._handoff_shield_to_radar(new_qty, curr_px):
                pass
            if not self._uses_dual_stop_track():
                radar = self._effective_radar_sl_for_merge() or None
                if radar:
                    self._sync_binance_merged_stop(
                        new_qty, radar_sl=radar, force_replace=True,
                    )
            consumed = sorted(getattr(self, "consumed_tp_levels", []) or [])
            remaining = defense.get("expected", 0)
            result.update({
                "defense": defense,
                "action_msg": (
                    f"TP{''.join(str(x) for x in consumed)}已成交"
                    f" → 剩余{remaining}档止盈+雷达锁润"
                ),
                "consumed_tp_levels": consumed,
            })
            if hasattr(self, "_alert"):
                self._alert(
                    "info",
                    "TP_FILLED",
                    f"止盈吃单·{cause}后对齐剩余档+雷达",
                    result["action_msg"]
                    + f" | 现价{float(curr_px or 0):.2f} | 头寸{old_qty}→{new_qty}",
                    result,
                )
            return result

        if cause == "manual_add":
            if hasattr(self, "consumed_tp_levels"):
                self.consumed_tp_levels = []
            self._reset_adverse_radar(keep_tv_sl=True)
            if hasattr(self, "initial_qty"):
                self.initial_qty = new_qty
            if float(getattr(self, "tv_sl", 0) or 0) > 0 and hasattr(self, "_sync_tv_hard_stop"):
                self._sync_tv_hard_stop(new_qty, force_replace=True)
            sl_to_pass = self._radar_sl_to_pass() if hasattr(self, "_radar_sl_to_pass") else None
            if hasattr(self, "_rebuild_defenses"):
                defense = self._rebuild_defenses(new_qty, entry, sl_to_pass)
                result.update({
                    "defense": defense,
                    "action_msg": "手动加仓 · 按新头寸重算 TP123",
                })
                return result

        sl_to_pass = self._radar_sl_to_pass() if hasattr(self, "_radar_sl_to_pass") else None
        action_labels = {
            "manual_add": "手动加仓",
            "manual_reduce": "手动减仓",
            "full_close": "人工全平",
        }
        action_msg = action_labels.get(cause, f"仓位异动 · {cause}")
        defense = self._smart_realign_defenses(
            new_qty,
            entry,
            dynamic_sl=sl_to_pass,
            reason=f"阵地异动: {action_msg}",
        )
        result.update({
            "defense": defense,
            "action_msg": action_msg,
            "consumed_tp_levels": sorted(getattr(self, "consumed_tp_levels", []) or []),
        })
        if hasattr(self, "_alert"):
            self._alert(
                "warning" if cause == "manual_reduce" else "info",
                "POSITION_QTY_CHANGE",
                f"仓位异动·{action_msg}",
                f"{old_qty}→{new_qty} @ {float(curr_px or 0):.2f} | "
                f"已消费TP{result['consumed_tp_levels']}",
                result,
            )
        return result
