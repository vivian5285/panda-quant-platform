"""Adverse-move radar: staged stop-loss when price moves against entry (VPS smart risk)."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.core.symbol_precision import round_price, round_quantity

logger = logging.getLogger(__name__)

# Arm staged stops when adverse price move reaches 2%; tiers at 2% / 3% / 5% from entry.
ADVERSE_ARM_PCT = 0.02
ADVERSE_SL_TIERS = (0.02, 0.03, 0.05)
ADVERSE_SL_SLICE_RATIOS = (0.33, 0.33, 0.34)
ADVERSE_STOP_TOLERANCE = 2.0


def adverse_move_pct(entry: float, price: float, side: str | None) -> float:
    """Positive fraction when price moved against the position (0 = flat or favorable)."""
    if entry <= 0 or price <= 0 or side not in ("LONG", "SHORT"):
        return 0.0
    if side == "LONG":
        return max(0.0, (entry - price) / entry)
    return max(0.0, (price - entry) / entry)


def compute_adverse_stop_plan(
    entry: float,
    side: str,
    live_qty: float,
    *,
    round_qty_fn,
) -> list[dict[str, Any]]:
    """Build 3-tier stop plan at 2%/3%/5% adverse prices with equal-ish qty slices."""
    if entry <= 0 or live_qty <= 0:
        return []
    slices = list(ADVERSE_SL_SLICE_RATIOS)
    qtys: list[float] = []
    allocated = 0.0
    for i, ratio in enumerate(slices):
        if i == len(slices) - 1:
            q = round_qty_fn(live_qty - allocated)
        else:
            q = round_qty_fn(live_qty * ratio)
            allocated += q
        if q > 0:
            qtys.append(q)

    plan: list[dict[str, Any]] = []
    for tier_pct, qty in zip(ADVERSE_SL_TIERS, qtys):
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


class AdverseRadarMixin:
    """Upgrade radar: favorable trail unchanged; adverse path arms staged stop-loss."""

    adverse_sl_armed: bool
    adverse_sl_prices: list[float]

    def _init_adverse_radar_fields(self) -> None:
        if not hasattr(self, "adverse_sl_armed"):
            self.adverse_sl_armed = False
        if not hasattr(self, "adverse_sl_prices"):
            self.adverse_sl_prices = []

    def _reset_adverse_radar(self) -> None:
        self.adverse_sl_armed = False
        self.adverse_sl_prices = []

    def _adverse_move_pct(self, curr_px: float) -> float:
        return adverse_move_pct(
            float(getattr(self, "watched_entry", 0) or 0),
            float(curr_px or 0),
            getattr(self, "current_side", None),
        )

    def _adverse_round_qty(self, qty: float) -> float:
        if getattr(self, "exchange_id", "") == "deepcoin":
            safe = getattr(self, "_safe_qty", lambda x: int(x))
            return float(max(int(safe(qty)), 1))
        return round_quantity(qty)

    def _compute_adverse_stop_plan(self, live_qty: float) -> list[dict[str, Any]]:
        return compute_adverse_stop_plan(
            float(self.watched_entry or 0),
            str(self.current_side or "LONG"),
            float(live_qty),
            round_qty_fn=self._adverse_round_qty,
        )

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
            order = client.place_trigger_order(
                symbol, close_side, pos_side, sz, stop_price,
                order_type="market", td_mode="cross", mrg_position="merge",
            )
            return order is not None

        if hasattr(client, "place_stop_market_order"):
            order = client.place_stop_market_order(
                close_side, stop_price, symbol, quantity=qty, reduce_only=True,
            )
            return order is not None
        return False

    def _collect_adverse_stop_orders(self) -> list[dict]:
        orders: list[dict] = []
        symbol = getattr(self, "symbol", None)
        targets = set(round(float(p), 2) for p in (self.adverse_sl_prices or []))

        if getattr(self, "exchange_id", "") == "deepcoin":
            try:
                pending = self.client.get_trigger_orders_pending(symbol) or []
                for o in pending:
                    px = float(o.get("triggerPrice", 0) or 0)
                    if targets and not any(abs(px - t) <= ADVERSE_STOP_TOLERANCE for t in targets):
                        continue
                    orders.append(o)
            except Exception:
                pass
            return orders

        for o in self.client.get_open_orders(symbol) or []:
            if o.get("type") not in ("STOP_MARKET", "STOP"):
                continue
            stop_px = 0.0
            for key in ("stopPrice", "triggerPrice", "activatePrice"):
                val = o.get(key)
                if val is not None and str(val).strip() not in ("", "0"):
                    try:
                        stop_px = round(float(val), 2)
                        break
                    except (TypeError, ValueError):
                        continue
            if targets and not any(abs(stop_px - t) <= ADVERSE_STOP_TOLERANCE for t in targets):
                if self.adverse_sl_armed and stop_px > 0:
                    entry = float(self.watched_entry or 0)
                    side = self.current_side
                    if side == "LONG" and stop_px < entry:
                        pass
                    elif side == "SHORT" and stop_px > entry:
                        pass
                    else:
                        continue
                else:
                    continue
            orders.append(o)
        return orders

    def _cancel_adverse_stop_orders(self) -> int:
        cancelled = 0
        symbol = getattr(self, "symbol", None)

        if getattr(self, "exchange_id", "") == "deepcoin":
            for o in self._collect_adverse_stop_orders():
                oid = o.get("ordId") or o.get("orderId")
                if oid:
                    self.client.cancel_trigger_order(symbol, oid)
                    cancelled += 1
                    time.sleep(0.2)
            return cancelled

        for o in self._collect_adverse_stop_orders():
            oid = o.get("orderId")
            if oid:
                self.client.cancel_order(symbol, int(oid))
                cancelled += 1
                time.sleep(0.2)
        return cancelled

    def _disarm_adverse_staged_stops(self) -> None:
        if not self.adverse_sl_armed:
            return
        n = self._cancel_adverse_stop_orders()
        self._reset_adverse_radar()
        if n > 0:
            logger.info("[User %s] adverse SL disarmed, cancelled %s stops", self.user_id, n)
        if hasattr(self, "_save_state"):
            self._save_state()

    def _verify_adverse_stops(self, plan: list[dict]) -> int:
        if not plan:
            return 0
        matched = 0
        open_stops = self._collect_adverse_stop_orders()
        for tier in plan:
            target = round(float(tier["stop_price"]), 2)
            for o in open_stops:
                for key in ("stopPrice", "triggerPrice", "activatePrice"):
                    val = o.get(key)
                    if val is None:
                        continue
                    try:
                        if abs(round(float(val), 2) - target) <= ADVERSE_STOP_TOLERANCE:
                            matched += 1
                            break
                    except (TypeError, ValueError):
                        continue
        return matched

    def _arm_adverse_staged_stops(self, live_qty: float, adverse_pct: float) -> dict[str, Any]:
        plan = self._compute_adverse_stop_plan(live_qty)
        if not plan:
            return {"armed": False, "reason": "empty_plan"}

        self._cancel_adverse_stop_orders()
        time.sleep(0.35)

        placed = 0
        prices: list[float] = []
        for tier in plan:
            ok = self._place_adverse_stop_slice(tier["stop_price"], tier["qty"])
            if ok:
                placed += 1
                prices.append(float(tier["stop_price"]))
            time.sleep(0.4)

        self.adverse_sl_armed = placed > 0
        self.adverse_sl_prices = prices
        verified = self._verify_adverse_stops(plan)

        detail = {
            "adverse_pct": round(adverse_pct * 100, 2),
            "entry": self.watched_entry,
            "side": self.current_side,
            "live_qty": live_qty,
            "plan": plan,
            "placed": placed,
            "verified": verified,
            "tiers": list(ADVERSE_SL_TIERS),
        }
        msg = (
            f"逆势分批止损已激活 | 浮亏 {detail['adverse_pct']:.1f}% | "
            f"挂出 {placed}/{len(plan)} 档 @ {[p['stop_price'] for p in plan]}"
        )
        self._log("ADVERSE_SL", msg, detail)
        self._alert("warning", "ADVERSE_SL", "智能风控 · 逆势分批止损", msg, detail)
        if hasattr(self, "_save_state"):
            self._save_state()
        return {"armed": self.adverse_sl_armed, "placed": placed, "verified": verified, "plan": plan}

    def _process_adverse_radar_guard(
        self, live_qty: float, curr_px: float, adverse_pct: float | None = None,
    ) -> bool:
        """
        Monitor adverse drift; arm 2/3/5% staged stops once drawdown >= 2%.
        Returns True if guard took action this tick.
        """
        self._init_adverse_radar_fields()
        if adverse_pct is None:
            adverse_pct = self._adverse_move_pct(curr_px)

        if adverse_pct < ADVERSE_ARM_PCT and not self.adverse_sl_armed:
            return False

        plan = self._compute_adverse_stop_plan(live_qty)
        if self.adverse_sl_armed:
            verified = self._verify_adverse_stops(plan)
            if verified < len(plan):
                logger.info(
                    "[User %s] adverse SL repair: %s/%s tiers present",
                    self.user_id, verified, len(plan),
                )
                return bool(self._arm_adverse_staged_stops(live_qty, adverse_pct).get("armed"))
            return False

        if adverse_pct >= ADVERSE_ARM_PCT:
            result = self._arm_adverse_staged_stops(live_qty, adverse_pct)
            return bool(result.get("armed"))
        return False
