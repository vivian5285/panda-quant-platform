"""Adverse-move radar + smart defense orchestration (浮盈/浮亏双轨防护)."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.core.position_qty_tolerance import qty_drift_tolerance
from app.core.symbol_precision import round_price, round_quantity

logger = logging.getLogger(__name__)

# Arm staged stops when adverse move reaches 3%; limit SL tiers at 3% / 4% / 5% from entry.
ADVERSE_ARM_PCT = 0.03
ADVERSE_SL_TIERS = (0.03, 0.04, 0.05)
ADVERSE_SL_SLICE_RATIOS = (0.33, 0.33, 0.34)
ADVERSE_STOP_TOLERANCE = 2.0
ADVERSE_REPAIR_COOLDOWN_SEC = 20.0
ADVERSE_MAX_TIER_ORDERS = len(ADVERSE_SL_TIERS)
QTY_MATCH_TOL_ETH = 0.005  # legacy alias; prefer qty_drift_tolerance()


def adverse_tier_stop_prices(entry: float, side: str) -> set[float]:
    """Entry-anchored 3/4/5% stop trigger prices for the active side."""
    if entry <= 0 or side not in ("LONG", "SHORT"):
        return set()
    prices: set[float] = set()
    for tier in ADVERSE_SL_TIERS:
        if side == "LONG":
            prices.add(round_price(entry * (1.0 - tier)))
        else:
            prices.add(round_price(entry * (1.0 + tier)))
    return prices


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
) -> list[dict[str, Any]]:
    """Build tiered stop plan; skip tiers already triggered by partial fills."""
    if entry <= 0 or live_qty <= 0:
        return []
    consumed = set(consumed_tiers or [])
    active_tiers = [t for t in ADVERSE_SL_TIERS if t not in consumed]
    if not active_tiers:
        return []

    slices = list(ADVERSE_SL_SLICE_RATIOS)
    # Re-normalize slice weights across remaining tiers only.
    tier_count = len(active_tiers)
    if tier_count == 1:
        weights = [1.0]
    elif tier_count == 2:
        weights = [0.5, 0.5]
    else:
        weights = list(slices)

    qtys: list[float] = []
    allocated = 0.0
    for i, _weight in enumerate(weights):
        if i == len(weights) - 1:
            q = round_qty_fn(live_qty - allocated)
        else:
            q = round_qty_fn(live_qty * weights[i])
            allocated += q
        if q > 0:
            qtys.append(q)

    plan: list[dict[str, Any]] = []
    for tier_pct, qty in zip(active_tiers, qtys):
        if qty <= 0:
            continue
        if side == "LONG":
            stop_px = round_price(entry * (1.0 - tier_pct))
        else:
            stop_px = round_price(entry * (1.0 + tier_pct))
        plan.append({
            "tier_pct": tier_pct,
            "stop_price": stop_px,
            "qty": qty,
            "level": len(plan) + 1,
        })
    return plan


def match_adverse_tier_fill(
    entry: float,
    side: str,
    old_qty: float,
    reduced_qty: float,
    *,
    round_qty_fn,
    qty_tol: float = QTY_MATCH_TOL_ETH,
) -> float | None:
    """If reduction matches an adverse tier slice, return that tier pct (0.03/0.04/0.05)."""
    if old_qty <= 0 or reduced_qty <= 0:
        return None
    plan = compute_adverse_stop_plan(entry, side, old_qty, round_qty_fn=round_qty_fn)
    for tier in plan:
        if abs(reduced_qty - float(tier["qty"])) <= qty_tol:
            return float(tier["tier_pct"])
    return None


class AdverseRadarMixin:
    """
    Dual-track VPS defense:
    - 浮盈: radar breakeven trail toward TP3 after TP fills
    - 浮亏: staged 3/4/5% limit stops from entry; partial hits keep deeper tiers
    """

    adverse_sl_armed: bool
    adverse_sl_prices: list[float]
    adverse_consumed_tiers: list[float]

    def _init_adverse_radar_fields(self) -> None:
        if not hasattr(self, "adverse_sl_armed"):
            self.adverse_sl_armed = False
        if not hasattr(self, "adverse_sl_prices"):
            self.adverse_sl_prices = []
        if not hasattr(self, "adverse_consumed_tiers"):
            self.adverse_consumed_tiers = []
        if not hasattr(self, "_adverse_last_repair_ts"):
            self._adverse_last_repair_ts = 0.0

    def _reset_adverse_radar(self) -> None:
        self.adverse_sl_armed = False
        self.adverse_sl_prices = []
        self.adverse_consumed_tiers = []
        self._adverse_last_repair_ts = 0.0

    def _adverse_tier_stop_prices(self) -> set[float]:
        return adverse_tier_stop_prices(
            float(self.watched_entry or 0),
            str(self.current_side or "LONG"),
        )

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
        return compute_adverse_stop_plan(
            float(self.watched_entry or 0),
            str(self.current_side or "LONG"),
            float(live_qty),
            round_qty_fn=self._adverse_round_qty,
            consumed_tiers=self._adverse_consumed_set(),
        )

    def _mark_adverse_tier_consumed(self, tier_pct: float) -> None:
        t = round(float(tier_pct), 4)
        if t not in self._adverse_consumed_set():
            self.adverse_consumed_tiers.append(t)
        self.adverse_sl_armed = True

    def _should_disarm_adverse_for_recovery(self, curr_px: float) -> bool:
        """Only disarm adverse shields when position is back to floating profit or radar locked."""
        if not self.adverse_sl_armed and not self.adverse_consumed_tiers:
            return False
        if self._is_floating_profit(curr_px):
            return True
        if hasattr(self, "_is_radar_active") and self._is_radar_active():
            return True
        return False

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

    def _classify_reduction_cause(self, old_qty: float, new_qty: float) -> str:
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
            return self._classify_qty_change(old_qty, new_qty)
        return "manual_reduce"

    def _adverse_close_side(self) -> str:
        if getattr(self, "exchange_id", "") == "deepcoin":
            return "sell" if self.current_side == "LONG" else "buy"
        return self._close_order_side()

    def _place_adverse_stop_slice(self, stop_price: float, qty: float) -> bool:
        close_side = self._adverse_close_side()
        symbol = getattr(self, "symbol", None)
        client = self.client

        if getattr(self, "exchange_id", "") == "deepcoin":
            pos_side = "long" if self.current_side == "LONG" else "short"
            sz = int(self._safe_qty(qty))
            if sz <= 0:
                return False
            limit_px = round_price(stop_price)
            order = client.place_trigger_order(
                symbol, close_side, pos_side, sz, limit_px,
                order_type="limit", price=limit_px, td_mode="cross", mrg_position="merge",
            )
            return order is not None

        limit_px = round_price(stop_price)
        if hasattr(client, "place_stop_limit_order"):
            order = client.place_stop_limit_order(
                close_side, stop_price, limit_px, symbol, quantity=qty, reduce_only=True,
            )
            return order is not None
        if hasattr(client, "place_stop_market_order"):
            order = client.place_stop_market_order(
                close_side, stop_price, symbol, quantity=qty, reduce_only=True,
            )
            return order is not None
        return False

    def _is_adverse_stop_order(self, o: dict, tier_prices: set[float]) -> bool:
        stop_px = _order_stop_price(o)
        if stop_px <= 0:
            return False
        if not any(abs(stop_px - t) <= ADVERSE_STOP_TOLERANCE for t in tier_prices):
            return False
        if getattr(self, "exchange_id", "") == "deepcoin":
            return True
        otype = str(o.get("type", "")).upper()
        if otype in ("STOP", "STOP_MARKET"):
            return True
        return False

    def _collect_adverse_stop_orders(self) -> list[dict]:
        orders: list[dict] = []
        symbol = getattr(self, "symbol", None)
        tier_prices = self._adverse_tier_stop_prices()

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

        for o in self.client.get_open_orders(symbol) or []:
            if self._is_adverse_stop_order(o, tier_prices):
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
            oid = o.get("orderId")
            if oid:
                self.client.cancel_order(symbol, int(oid))
                cancelled += 1
                time.sleep(0.2)
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
                live_q = _order_qty_value(o)
                if abs(live_q - target_qty) > qty_tol:
                    continue
                matched += 1
                if oid is not None:
                    used_ids.add(oid)
                break
        return matched

    def _adverse_stops_need_repair(self, plan: list[dict]) -> bool:
        if not plan:
            return False
        open_count = len(self._collect_adverse_stop_orders())
        verified = self._verify_adverse_stops(plan)
        if verified >= len(plan):
            return False
        if open_count > ADVERSE_MAX_TIER_ORDERS:
            return True
        return verified < len(plan)

    def _can_repair_adverse_stops(self) -> bool:
        return (time.time() - float(getattr(self, "_adverse_last_repair_ts", 0) or 0)) >= ADVERSE_REPAIR_COOLDOWN_SEC

    def _disarm_adverse_staged_stops(self, *, reason: str = "recovery") -> None:
        if not self.adverse_sl_armed and not self.adverse_consumed_tiers:
            return
        n = self._cancel_adverse_stop_orders()
        self.adverse_sl_armed = False
        self.adverse_sl_prices = []
        self.adverse_consumed_tiers = []
        self._adverse_last_repair_ts = 0.0
        if n > 0:
            logger.info(
                "[User %s] adverse SL disarmed (%s), cancelled %s stops",
                self.user_id, reason, n,
            )
        if hasattr(self, "_save_state"):
            self._save_state()

    def _arm_adverse_staged_stops(
        self, live_qty: float, adverse_pct: float, *, repair: bool = False,
    ) -> dict[str, Any]:
        live_qty = self._resolve_adverse_live_qty(live_qty)
        if live_qty <= 0:
            return {"armed": False, "reason": "no_live_position", "live_qty": 0}

        plan = self._compute_adverse_stop_plan(live_qty)
        if not plan:
            if self.adverse_consumed_tiers:
                self.adverse_sl_armed = True
            return {"armed": False, "reason": "all_tiers_consumed", "consumed": list(self.adverse_consumed_tiers)}

        verified_before = self._verify_adverse_stops(plan)
        if not repair and self.adverse_sl_armed and verified_before >= len(plan):
            return {
                "armed": True,
                "placed": 0,
                "verified": verified_before,
                "plan": plan,
                "skipped": "already_aligned",
            }

        cancelled = self._cancel_adverse_stop_orders()
        if cancelled:
            time.sleep(0.35)
        elif repair:
            time.sleep(0.25)
        else:
            time.sleep(0.15)

        placed = 0
        prices: list[float] = []
        for tier in plan:
            ok = self._place_adverse_stop_slice(tier["stop_price"], tier["qty"])
            if ok:
                placed += 1
                prices.append(float(tier["stop_price"]))
            time.sleep(0.4)

        time.sleep(0.5)
        purged = self._purge_excess_adverse_stops(plan)
        verified = self._verify_adverse_stops(plan)
        open_count = len(self._collect_adverse_stop_orders())

        self.adverse_sl_armed = placed > 0 or bool(self.adverse_consumed_tiers) or verified > 0
        self.adverse_sl_prices = prices or [float(t["stop_price"]) for t in plan]
        self._adverse_last_repair_ts = time.time()

        detail = {
            "adverse_pct": round(adverse_pct * 100, 2),
            "entry": self.watched_entry,
            "side": self.current_side,
            "exchange": getattr(self, "exchange_id", "binance"),
            "live_qty": live_qty,
            "plan": plan,
            "placed": placed,
            "verified": verified,
            "open_adverse_stops": open_count,
            "cancelled_before_place": cancelled,
            "purged_duplicates": purged,
            "consumed_tiers": list(self.adverse_consumed_tiers),
            "tiers": list(ADVERSE_SL_TIERS),
            "repair": repair,
        }
        if not repair:
            msg = (
                f"逆势分批止损已激活 | 浮亏 {detail['adverse_pct']:.1f}% | "
                f"挂出 {placed}/{len(plan)} 档 @ {[p['stop_price'] for p in plan]}"
            )
            self._log("ADVERSE_SL", msg, detail)
            self._alert("warning", "ADVERSE_SL", "智能风控 · 逆势分批止损", msg, detail)
        else:
            msg = (
                f"逆势止损补挂 | 剩余 {placed}/{len(plan)} 档 | "
                f"已触发 {detail['consumed_tiers']}"
            )
            self._log("ADVERSE_SL_REPAIR", msg, detail)
        if hasattr(self, "_save_state"):
            self._save_state()
        return {"armed": self.adverse_sl_armed, "placed": placed, "verified": verified, "plan": plan}

    def _repair_adverse_stops_remaining(self, live_qty: float, adverse_pct: float) -> dict[str, Any]:
        return self._arm_adverse_staged_stops(live_qty, adverse_pct, repair=True)

    def _process_adverse_radar_guard(
        self, live_qty: float, curr_px: float, adverse_pct: float | None = None,
    ) -> bool:
        self._init_adverse_radar_fields()
        if adverse_pct is None:
            adverse_pct = self._adverse_move_pct(curr_px)

        live_qty = self._resolve_adverse_live_qty(live_qty)
        if live_qty <= 0:
            return False

        if adverse_pct < ADVERSE_ARM_PCT and not self.adverse_sl_armed and not self.adverse_consumed_tiers:
            return False

        plan = self._compute_adverse_stop_plan(live_qty)
        if self.adverse_sl_armed or self.adverse_consumed_tiers:
            if plan and not self._adverse_stops_need_repair(plan):
                return False
            if plan and self._can_repair_adverse_stops():
                return bool(
                    self._repair_adverse_stops_remaining(live_qty, adverse_pct).get("armed")
                )
            if len(self._collect_adverse_stop_orders()) > ADVERSE_MAX_TIER_ORDERS and self._can_repair_adverse_stops():
                purged = self._purge_excess_adverse_stops(plan)
                if purged:
                    logger.warning(
                        "[User %s] adverse SL purged %s duplicate stops (open>%s)",
                        self.user_id, purged, ADVERSE_MAX_TIER_ORDERS,
                    )
            return False

        if adverse_pct >= ADVERSE_ARM_PCT:
            return bool(self._arm_adverse_staged_stops(live_qty, adverse_pct).get("armed"))
        return False

    def _boost_radar_after_tp_fill(self, change_type: str, curr_px: float, live_qty: float) -> None:
        """After TP1/TP2 eaten: lock breakeven and trail radar toward TP3."""
        if change_type not in ("tp1_filled", "tp2_filled", "tp3_filled"):
            return
        entry = float(self.watched_entry or 0)
        if entry <= 0:
            return
        fee_buffer = entry * 0.0015
        tp3 = float(self.tv_tps[2]) if len(getattr(self, "tv_tps", []) or []) > 2 else 0.0

        if self.current_side == "LONG":
            floor_sl = round_price(entry + fee_buffer)
            if float(getattr(self, "current_sl", 0) or 0) < floor_sl:
                self.current_sl = floor_sl
            if curr_px > 0:
                self.best_price = max(float(getattr(self, "best_price", entry) or entry), curr_px)
            if tp3 > entry and curr_px > 0:
                trail = round_price(max(self.current_sl, curr_px - self.current_atr * 0.5))
                if trail > self.current_sl:
                    self.current_sl = min(trail, round_price(tp3 * 0.995))
        else:
            floor_sl = round_price(entry - fee_buffer)
            if float(getattr(self, "current_sl", 0) or 0) <= 0 or self.current_sl > floor_sl:
                self.current_sl = floor_sl
            if curr_px > 0:
                self.best_price = min(float(getattr(self, "best_price", entry) or entry), curr_px)
            if tp3 > 0 and tp3 < entry and curr_px > 0:
                trail = round_price(min(self.current_sl, curr_px + self.current_atr * 0.5))
                if trail < self.current_sl:
                    self.current_sl = max(trail, round_price(tp3 * 1.005))

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
        Sentinel price-defense branch:
        - 浮盈 / 雷达激活 → trailing radar; disarm adverse only on 浮盈 recovery
        - 浮亏 >= 3% → staged 3/4/5% limit stops from entry (keep deeper tiers on partial hits)
        """
        if curr_px <= 0:
            return

        adverse_pct = self._adverse_move_pct(curr_px)
        if self._should_disarm_adverse_for_recovery(curr_px):
            self._disarm_adverse_staged_stops(reason="floating_profit_recovery")
            self._log(
                "RECOVERY",
                f"浮盈恢复 · 撤销逆势止损盾，切换雷达保本 | 现价 {curr_px:.2f}",
                {"entry": self.watched_entry, "price": curr_px, "side": self.current_side},
            )

        progress = self._radar_activation_progress(curr_px) if hasattr(self, "_radar_activation_progress") else 0.0
        radar_ready = self._is_radar_active() or progress >= 1.0

        if radar_ready and (self._is_floating_profit(curr_px) or self._is_radar_active()):
            if hasattr(self, "_process_radar_trailing"):
                self._process_radar_trailing(live_qty, curr_px)
        elif adverse_pct >= ADVERSE_ARM_PCT or self.adverse_sl_armed or self.adverse_consumed_tiers:
            self._process_adverse_radar_guard(live_qty, curr_px, adverse_pct)
        elif progress >= 0.5 and getattr(self, "_scan_ticks", 0) % 5 == 0:
            logger.info(
                "[User %s] 📡 雷达预热: 进度 %.0f%% | 现价 %.2f",
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
        cause = self._classify_reduction_cause(old_qty, new_qty)
        result: dict[str, Any] = {"change_type": cause, "old_qty": old_qty, "new_qty": new_qty}

        if cause.startswith("adverse_sl_"):
            tier_key = cause.replace("adverse_sl_", "").replace("pct", "")
            try:
                tier_pct = int(tier_key) / 100.0
            except ValueError:
                tier_pct = 0.03
            self._mark_adverse_tier_consumed(tier_pct)
            adverse_pct = self._adverse_move_pct(curr_px)
            repair = self._repair_adverse_stops_remaining(new_qty, adverse_pct)
            tp_result = self._smart_realign_defenses(
                new_qty,
                entry,
                dynamic_sl=None,
                reason=f"逆势止损触发 · {cause} · 保留更深档位",
            )
            result.update({"defense": tp_result, "adverse_repair": repair, "action_msg": f"逆势止损 · {cause}"})
            self._alert(
                "warning",
                "ADVERSE_SL_HIT",
                "防护盾触发",
                f"{cause} 减仓 {old_qty}→{new_qty}，已补挂剩余止损档",
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
                reason=f"止盈吃单 · {cause}",
            )
            result.update({
                "defense": defense,
                "action_msg": f"部分止盈吃单 · {cause}",
            })
            return result

        if cause == "manual_add":
            if hasattr(self, "consumed_tp_levels"):
                self.consumed_tp_levels = []
            self._reset_adverse_radar()

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
