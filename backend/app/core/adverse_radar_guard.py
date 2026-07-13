"""Adverse-move radar + TV hard stop orchestration (浮盈雷达 / TV tv_sl 防护)."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.core.position_qty_tolerance import qty_drift_tolerance
from app.core.radar_trail import (
    RADAR_STARTUP_PROFIT_PROGRESS,
    clamp_stop_market_safe,
    stop_would_trigger_immediately,
    tp1_distance,
    tp_path_progress,
)
from app.core.vps_hard_sl import compute_hard_sl_limit_price, compute_vps_hard_sl
from app.core.vps_radar_stages import compute_vps_radar_sl, detect_radar_stage
from app.core.symbol_precision import round_price, round_quantity

logger = logging.getLogger(__name__)

# TV hard stop from webhook tv_sl; legacy 10% kept only for fill-attribution helpers.
ADVERSE_HARD_STOP_PCT = 0.10
TV_SL_TIER_MARKER = -1.0  # plan tier_pct when stop price comes from TV
ADVERSE_STOP_TOLERANCE = 2.0
ADVERSE_REPAIR_COOLDOWN_SEC = 20.0
ADVERSE_MAX_STOP_ORDERS = 1
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
    """Recognize STOP on regular book and Binance algo conditional book."""
    otype = str(o.get("type") or o.get("orderType") or "").upper()
    if otype in ("STOP_MARKET", "STOP"):
        return True
    if o.get("isAlgoOrder") and _order_stop_price(o) > 0:
        if otype in ("", "CONDITIONAL") or otype.endswith("_MARKET"):
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
        "source": "vps_hard_sl",
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
    Dual-track VPS defense:
    - 开仓: TV tv_sl 硬止损全平（挂一次，实盘核实）
    - 朝 TP1: 达雷达激活比例 → 雷达保本移动止损（不低于 TV 底线）
    """

    adverse_sl_armed: bool
    adverse_sl_prices: list[float]
    adverse_consumed_tiers: list[float]

    def _init_adverse_radar_fields(self) -> None:
        if not hasattr(self, "tv_sl"):
            self.tv_sl = 0.0
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

    def _reset_adverse_radar(self, *, keep_tv_sl: bool = True) -> None:
        preserved = float(getattr(self, "tv_sl", 0) or 0) if keep_tv_sl else 0.0
        self.adverse_sl_armed = False
        self.adverse_sl_prices = []
        self.adverse_consumed_tiers = []
        self._adverse_last_repair_ts = 0.0
        self.adverse_arm_dingtalk_sent = False
        self._pending_adverse_algo_ids = []
        self.tv_sl = preserved

    def _hard_stop_label(self) -> str:
        return "VPS硬止损"

    def _recompute_vps_hard_sl(
        self,
        entry_px: float | None = None,
        *,
        payload: dict | None = None,
        side: str | None = None,
    ) -> dict:
        """Authoritative hard SL from regime × ATR (TV tv_sl reference-only)."""
        from app.config import get_settings

        self._init_adverse_radar_fields()
        entry = float(
            entry_px
            or getattr(self, "watched_entry", 0)
            or getattr(self, "tv_price", 0)
            or 0
        )
        if payload:
            entry = float(payload.get("price") or entry or 0)
        atr = float(getattr(self, "current_atr", 0) or 0)
        if payload and payload.get("atr"):
            atr = float(payload.get("atr") or atr)
        regime = int(getattr(self, "regime", 3) or 3)
        if payload and payload.get("regime") is not None:
            regime = int(payload.get("regime") or regime)
        side_u = side or getattr(self, "current_side", None)
        if not side_u and payload:
            act = str(payload.get("action") or "").upper()
            if "LONG" in act:
                side_u = "LONG"
            elif "SHORT" in act:
                side_u = "SHORT"
            elif payload.get("side"):
                side_u = str(payload.get("side")).upper()

        relax = float(getattr(get_settings(), "VPS_SL_RELAX_PCT", 0) or 0)
        ref = parse_tv_sl(payload.get("tv_sl")) if payload else None
        meta = compute_vps_hard_sl(
            entry, side_u, atr, regime,
            relax_pct=relax,
            tv_sl_reference=ref,
        )
        if meta.get("stop_price", 0) > 0:
            self.tv_sl = float(meta["stop_price"])
            self._vps_hard_sl_meta = meta
        logger.info(
            "VPS硬止损计算: entry=%.2f side=%s regime=%s atr=%.2f → stop=%.2f | %s",
            entry,
            side_u,
            regime,
            atr,
            float(meta.get("stop_price") or 0),
            meta,
        )
        return meta

    def _apply_tv_sl_from_payload(self, payload: dict | None) -> float | None:
        """Compute VPS hard SL from regime+ATR; TV tv_sl stored as reference only."""
        if not payload:
            return None
        meta = self._recompute_vps_hard_sl(payload=payload)
        px = float(meta.get("stop_price") or 0)
        return px if px > 0 else None

    def _clamp_radar_sl_to_tv_floor(self, sl: float) -> float:
        """Radar must never sit below VPS hard stop (LONG) or above it (SHORT)."""
        tv_sl = float(getattr(self, "tv_sl", 0) or 0)
        if tv_sl <= 0 or sl <= 0:
            return sl
        side = getattr(self, "current_side", None)
        if side == "LONG":
            return round_price(max(sl, tv_sl))
        if side == "SHORT":
            return round_price(min(sl, tv_sl))
        return sl

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
        """Deepcoin: TV底线 + 雷达双轨；其余交易所 Binance 类合并单槽。"""
        return getattr(self, "exchange_id", "") == "deepcoin"

    def _effective_radar_sl_for_merge(self) -> float:
        if hasattr(self, "_is_radar_active") and self._is_radar_active():
            return float(getattr(self, "current_sl", 0) or 0)
        return 0.0

    def _merged_stop_price(self, radar_sl: float | None = None) -> float:
        """Binance 单槽：LONG max(tv_sl, radar)，SHORT min。"""
        tv = float(getattr(self, "tv_sl", 0) or 0)
        radar = float(
            radar_sl if radar_sl is not None else self._effective_radar_sl_for_merge()
        )
        side = getattr(self, "current_side", None)
        if side == "LONG":
            parts = [p for p in (tv, radar) if p > 0]
            return round_price(max(parts)) if parts else 0.0
        if side == "SHORT":
            parts = [p for p in (tv, radar) if p > 0]
            return round_price(min(parts)) if parts else 0.0
        return 0.0

    def _shield_tier_prices(self) -> set[float]:
        """All stop trigger prices used to identify TV/legacy hard stops on the book."""
        prices = set(self._adverse_tier_stop_prices())
        for px in (self.adverse_sl_prices or []):
            try:
                p = round(float(px), 2)
                if p > 0:
                    prices.add(p)
            except (TypeError, ValueError):
                continue
        return prices

    def _adverse_tier_stop_prices(self) -> set[float]:
        if not self._uses_dual_stop_track():
            merged = self._merged_stop_price()
            if merged > 0:
                return {merged}
        tv_sl = float(getattr(self, "tv_sl", 0) or 0)
        if tv_sl > 0:
            return {round_price(tv_sl)}
        return set()

    def _cancel_binance_all_close_stops(self) -> int:
        """Cancel every STOP closePosition on book before replacing merged slot."""
        if self._uses_dual_stop_track():
            return 0
        symbol = getattr(self, "symbol", None)
        client = getattr(self, "client", None)
        if not symbol or not client:
            return 0
        cancelled = 0
        seen: set[str | int] = set()
        for o in client.get_open_orders(symbol) or []:
            if not _is_stop_market_like(o):
                continue
            oid = o.get("algoId") or o.get("orderId")
            if oid is None or oid in seen:
                continue
            seen.add(oid)
            client.cancel_order(symbol, int(oid))
            cancelled += 1
            time.sleep(0.2)
        for o in self._collect_pending_adverse_algo_orders(set()):
            oid = o.get("algoId") or o.get("orderId")
            if oid is None or oid in seen:
                continue
            seen.add(oid)
            client.cancel_order(symbol, int(oid))
            cancelled += 1
            time.sleep(0.2)
        if cancelled:
            self._pending_adverse_algo_ids = []
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

        effective = self._merged_stop_price(radar_sl)
        if effective <= 0:
            return {"armed": False, "reason": "no_tv_sl_or_radar"}

        side = getattr(self, "current_side", None)
        open_stops = self._collect_adverse_stop_orders()
        live_stop_px = (
            _order_stop_price(open_stops[0]) if open_stops else 0.0
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
                        _order_stop_price(open_stops[0])
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
        if audit.get("aligned") and not force_replace:
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
        placed = 1 if self._place_adverse_stop_slice(effective, live_qty) else 0
        if placed:
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
        tv_sl = float(getattr(self, "tv_sl", 0) or 0)
        return compute_adverse_stop_plan(
            float(self.watched_entry or 0),
            str(self.current_side or "LONG"),
            float(live_qty),
            round_qty_fn=self._adverse_round_qty,
            consumed_tiers=self._adverse_consumed_set(),
            tv_sl_price=tv_sl if tv_sl > 0 else None,
        )

    def _sync_tv_hard_stop(
        self,
        live_qty: float,
        *,
        at_open: bool = False,
        force_replace: bool = False,
    ) -> dict[str, Any]:
        """Arm TV hard stop — Deepcoin 独立底线；其余交易所走合并单槽。"""
        if not self._uses_dual_stop_track():
            radar = self._effective_radar_sl_for_merge() or None
            return self._sync_binance_merged_stop(
                live_qty, radar_sl=radar, force_replace=force_replace, at_open=at_open,
            )

        live_qty = self._resolve_adverse_live_qty(live_qty)
        if live_qty <= 0:
            return {"armed": False, "reason": "no_live_position", "live_qty": 0}

        label = self._hard_stop_label()
        tv_sl = float(getattr(self, "tv_sl", 0) or 0)
        if not force_replace:
            audit = self._sync_adverse_shield_from_exchange(live_qty)
            if audit.get("aligned"):
                stop_px = (audit.get("plan") or [{}])[0].get("stop_price") or tv_sl
                return {
                    "armed": True,
                    "placed": 0,
                    "skipped": "live_already_aligned",
                    "stop_price": stop_px,
                    "label": label,
                    **audit,
                }

        if force_replace or (tv_sl > 0 and not at_open):
            self._cancel_adverse_stop_orders()
            self.adverse_sl_armed = False
            self.adverse_sl_prices = []

        if at_open and tv_sl <= 0:
            return {"armed": False, "reason": "no_tv_sl", "skipped": "await_tv_sl"}

        return self._arm_adverse_staged_stops(
            live_qty, 0.0, repair=force_replace or tv_sl > 0, at_open=at_open,
        )

    def _handle_update_sl(self, payload: dict) -> dict[str, Any]:
        """UPDATE_SL ignored — VPS computes hard SL from regime+ATR; radar managed locally."""
        self._init_adverse_radar_fields()
        detail: dict[str, Any] = {
            "action": "UPDATE_SL",
            "ignored": True,
            "reason": "vps_self_managed",
            "note": "VPS 自主计算硬止损与雷达，忽略 TV UPDATE_SL",
            "tv_sl_reference": parse_tv_sl(payload.get("tv_sl")),
            "vps_sl": float(getattr(self, "tv_sl", 0) or 0),
            "regime": getattr(self, "regime", None),
            "atr": getattr(self, "current_atr", None),
        }
        self._log("UPDATE_SL", "忽略 TV UPDATE_SL — VPS 自主管理硬止损", detail)
        return {
            "status": "skipped",
            "reason": "update_sl_ignored",
            "action": "UPDATE_SL",
            "detail": detail,
        }

    def _mark_adverse_tier_consumed(self, tier_pct: float) -> None:
        t = round(float(tier_pct), 4)
        if t not in self._adverse_consumed_set():
            self.adverse_consumed_tiers.append(t)
        self.adverse_sl_armed = True

    def _radar_activation_reached(self, curr_px: float) -> bool:
        """True when 8-stage radar may arm (stage≥1, TP1 filled, or already trailing)."""
        if hasattr(self, "_is_radar_active") and self._is_radar_active():
            return True
        consumed = list(getattr(self, "consumed_tp_levels", []) or [])
        if consumed:
            return True
        entry = float(getattr(self, "watched_entry", 0) or 0)
        tps = list(getattr(self, "tv_tps", []) or [])
        tp1 = float(tps[0] or 0) if tps else 0.0
        tp2 = float(tps[1] or 0) if len(tps) > 1 else 0.0
        tp3 = float(tps[2] or 0) if len(tps) > 2 else 0.0
        stage = detect_radar_stage(
            entry, curr_px, getattr(self, "current_side", None), tp1, tp2, tp3,
        )
        return stage >= 1

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
        reason: str = "radar_tp1_activation",
        notify: bool = False,
    ) -> dict[str, Any]:
        """Route A: 不撤 TV 硬止损；Binance 由合并单槽表达双层语义。"""
        return {"cancelled": 0, "skipped": "route_a_coexist", "reason": reason}

    def _handoff_shield_to_radar(self, live_qty: float, curr_px: float) -> bool:
        """After shield disarm: activate radar breakeven trail when TP1 distance is met."""
        if curr_px <= 0:
            return False
        progress = (
            self._radar_activation_progress(curr_px)
            if hasattr(self, "_radar_activation_progress")
            else 0.0
        )
        consumed = list(getattr(self, "consumed_tp_levels", []) or [])
        radar_mem = bool(hasattr(self, "_is_radar_active") and self._is_radar_active())
        if progress < 1.0 and not radar_mem and not consumed:
            return False
        live_qty = self._resolve_adverse_live_qty(live_qty)
        if hasattr(self, "_refresh_radar_state_on_recover"):
            self._refresh_radar_state_on_recover(curr_px, float(self.watched_entry or 0))

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
            return bool(self._has_stop_sl_near(sl_px))
        if sl_px > 0 and hasattr(self, "_has_trigger_sl_near"):
            return bool(self._has_trigger_sl_near(sl_px))
        return placed

    def _classify_tp_reduction(self, old_qty: float, new_qty: float) -> str | None:
        if new_qty <= 0 or new_qty >= old_qty - self._qty_match_tol(old_qty, new_qty):
            return None
        if hasattr(self, "_classify_qty_change"):
            cause = self._classify_qty_change(old_qty, new_qty)
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

        tp_cause = self._classify_tp_reduction(old_qty, new_qty)
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

    def _place_adverse_stop_slice(self, stop_price: float, qty: float) -> bool:
        """Place buffer hard stop — prefer Stop-Limit (trigger + limit offset)."""
        close_side = self._adverse_close_side()
        symbol = getattr(self, "symbol", None)
        client = self.client

        if getattr(self, "exchange_id", "") == "deepcoin":
            pos_side = "long" if self.current_side == "LONG" else "short"
            sz = int(self._safe_qty(qty))
            if sz <= 0:
                return False
            trigger_px = round_price(stop_price)
            order = client.place_trigger_order(
                symbol, close_side, pos_side, sz, trigger_px,
                order_type="market", td_mode="cross", mrg_position="merge",
            )
            return order is not None

        limit_px = self._hard_sl_limit_price(stop_price)
        if hasattr(client, "place_stop_limit_order"):
            order = client.place_stop_limit_order(
                close_side, stop_price, limit_px, symbol,
                quantity=qty, reduce_only=True,
            )
            if order:
                return True

        if hasattr(client, "place_stop_market_order"):
            order = client.place_stop_market_order(
                close_side, stop_price, symbol, quantity=None,
            )
            if order:
                aid = order.get("algoId") or order.get("orderId")
                if aid:
                    pending = list(getattr(self, "_pending_adverse_algo_ids", None) or [])
                    aid_int = int(aid)
                    if aid_int not in pending:
                        pending.append(aid_int)
                    self._pending_adverse_algo_ids = pending[-8:]
                return True
        return False

    def _is_adverse_stop_order(self, o: dict, tier_prices: set[float]) -> bool:
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
            close_side = str(self._adverse_close_side() or "").upper()
            order_side = str(o.get("side", "")).upper()
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
            px = _order_stop_price(o)
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
                oid = extra.get("orderId") or extra.get("ordId")
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
                if abs(_order_stop_price(o) - target_px) <= ADVERSE_STOP_TOLERANCE:
                    matched += 1
                    break
        return matched

    def _tier_has_live_stop(self, tier: dict[str, Any], open_stops: list[dict]) -> bool:
        target_px = round(float(tier["stop_price"]), 2)
        target_qty = float(tier["qty"])
        qty_tol = self._qty_match_tol(target_qty, target_qty)
        for o in open_stops:
            if abs(_order_stop_price(o) - target_px) > ADVERSE_STOP_TOLERANCE:
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
            "TV硬止损未对齐",
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
                _order_stop_price(o) for o in open_stops if _order_stop_price(o) > 0
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
                if _is_stop_market_like(o) or _order_stop_price(o) > 0:
                    open_stops.append(o)
        live_px = _order_stop_price(open_stops[0]) if open_stops else 0.0

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
                stop_px = _order_stop_price(o)
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
            stop_px = float(getattr(self, "tv_sl", 0) or 0)
            label = self._hard_stop_label()
            msg = (
                f"雷达接管 · {reason} | 已撤 {label} {n} 笔"
                + (f" @{stop_px:.2f}" if stop_px > 0 else "")
            )
            self._log("ADVERSE_SL_DISARM", msg, result)
            self._alert(
                "info",
                "ADVERSE_SL_DISARM",
                "防护盾撤销 · 雷达保本接管",
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
        10% hard stop arm sequence (exchange-first):
        1) sync live position + open stops
        2) skip if already aligned
        3) purge duplicates only
        4) place ONLY if missing (never cancel-all + blind re-arm)
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
            "stop_price": plan[0]["stop_price"] if plan else adverse_hard_stop_price(
                float(self.watched_entry or 0), str(self.current_side or "LONG"),
            ),
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
            self._alert("warning", "ADVERSE_SL", f"防护盾 · {label}", msg, detail)
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
        if progress >= 1.0 or (hasattr(self, "_is_radar_active") and self._is_radar_active()):
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
        """After TP1/TP2 eaten: lock breakeven with regime trail width toward TP3."""
        if change_type not in ("tp1_filled", "tp2_filled", "tp3_filled"):
            return
        entry = float(self.watched_entry or 0)
        if entry <= 0:
            return
        tps = list(getattr(self, "tv_tps", []) or [])
        tp1 = float(tps[0] or 0) if tps else 0.0
        tp2 = float(tps[1] or 0) if len(tps) > 1 else 0.0
        tp3 = float(tps[2] or 0) if len(tps) > 2 else 0.0
        if curr_px > 0:
            if self.current_side == "LONG":
                self.best_price = max(float(getattr(self, "best_price", entry) or entry), curr_px)
            else:
                self.best_price = min(float(getattr(self, "best_price", entry) or entry), curr_px)
        radar = compute_vps_radar_sl(
            entry=entry,
            curr_px=float(curr_px or entry),
            best_price=float(self.best_price or entry),
            atr=self.current_atr,
            side=self.current_side,
            tp1=tp1, tp2=tp2, tp3=tp3,
            old_sl=float(getattr(self, "current_sl", 0) or 0),
            hard_sl=float(getattr(self, "tv_sl", 0) or 0),
            clamp_fn=getattr(self, "_clamp_radar_sl_to_tv_floor", lambda x: x),
        )
        if radar.get("armed") and radar.get("radar_sl", 0) > 0:
            self.current_sl = float(radar["radar_sl"])

        if hasattr(self, "_realign_radar_defenses"):
            self._realign_radar_defenses(live_qty, entry, self.current_sl)
        elif hasattr(self, "_smart_realign_defenses"):
            self._smart_realign_defenses(
                live_qty, entry, dynamic_sl=self.current_sl, reason=f"TP吃单后雷达朝TP3推进 · {change_type}",
            )
        if hasattr(self, "_save_state"):
            self._save_state()

    def _orchestrate_defense_monitoring(self, live_qty: float, curr_px: float) -> None:
        """
        Route A 三层分工：TV底线 + 雷达追踪 + TP123。
        雷达激活时不撤 TV 止损；Binance 合并单槽，Deepcoin 双轨并行。
        """
        if curr_px <= 0:
            return

        live_qty = self._resolve_adverse_live_qty(live_qty)
        if hasattr(self, "_sync_consumed_tp_levels"):
            self._sync_consumed_tp_levels(live_qty, curr_px)
        progress = self._radar_activation_progress(curr_px) if hasattr(self, "_radar_activation_progress") else 0.0

        if self._radar_activation_reached(curr_px):
            if hasattr(self, "_process_radar_trailing"):
                self._process_radar_trailing(live_qty, curr_px)
            elif self._handoff_shield_to_radar(live_qty, curr_px):
                pass
            if self._uses_dual_stop_track():
                self._process_adverse_radar_guard(live_qty, curr_px)
            else:
                radar = self._effective_radar_sl_for_merge() or None
                self._sync_binance_merged_stop(
                    live_qty, radar_sl=radar, force_replace=bool(radar),
                )
            return

        self._process_adverse_radar_guard(live_qty, curr_px)

        if progress >= 0.5 and getattr(self, "_scan_ticks", 0) % 5 == 0:
            logger.info(
                "[User %s] 📡 雷达预热: 进度 %.0f%% | 现价 %.2f | TV底线守护中",
                self.user_id, progress * 100, curr_px,
            )

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
                reason=f"TV硬止损触发 · {cause}",
            )
            result.update({
                "defense": tp_result,
                "action_msg": f"TV硬止损全平 · {cause}",
            })
            self._alert(
                "critical",
                "ADVERSE_SL_HIT",
                "TV硬止损触发",
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
                reason=f"止盈吃单 · {cause} · 仅挂剩余TP+雷达",
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
            })
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
        result.update({"defense": defense, "action_msg": action_msg})
        return result
