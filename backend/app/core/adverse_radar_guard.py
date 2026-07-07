"""Adverse-move radar + smart defense orchestration (浮盈雷达 / 开仓10%硬止损防护盾)."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.core.position_qty_tolerance import qty_drift_tolerance
from app.core.symbol_precision import round_price, round_quantity

logger = logging.getLogger(__name__)

# Single hard stop at open: 10% adverse move from entry → full close (ETH price anchor).
ADVERSE_HARD_STOP_PCT = 0.10
ADVERSE_STOP_TOLERANCE = 2.0
ADVERSE_REPAIR_COOLDOWN_SEC = 20.0
ADVERSE_MAX_STOP_ORDERS = 1
ADVERSE_VERIFY_RETRIES = 4
ADVERSE_VERIFY_RETRY_DELAY_SEC = 0.35
# Legacy aliases (tests / imports)
ADVERSE_ARM_PCT = ADVERSE_HARD_STOP_PCT
ADVERSE_SL_TIERS = (ADVERSE_HARD_STOP_PCT,)
ADVERSE_MAX_TIER_ORDERS = ADVERSE_MAX_STOP_ORDERS


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
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1")
    return bool(val)


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
) -> list[dict[str, Any]]:
    """Single 10% hard stop — full live qty, one order."""
    if entry <= 0 or live_qty <= 0:
        return []
    consumed = set(consumed_tiers or [])
    if ADVERSE_HARD_STOP_PCT in consumed or any(
        abs(float(t) - ADVERSE_HARD_STOP_PCT) < 1e-6 for t in consumed
    ):
        return []
    qty = round_qty_fn(live_qty)
    if qty <= 0:
        return []
    stop_px = adverse_hard_stop_price(entry, side)
    if stop_px <= 0:
        return []
    return [{
        "tier_pct": ADVERSE_HARD_STOP_PCT,
        "stop_price": stop_px,
        "qty": qty,
        "level": 1,
    }]


def match_adverse_tier_fill(
    entry: float,
    side: str,
    old_qty: float,
    reduced_qty: float,
    *,
    round_qty_fn,
    qty_tol: float | None = None,
) -> float | None:
    """If reduction matches full-position 10% hard stop, return tier pct."""
    if old_qty <= 0 or reduced_qty <= 0:
        return None
    tol = qty_tol if qty_tol is not None else qty_drift_tolerance(old_qty, old_qty)
    plan = compute_adverse_stop_plan(entry, side, old_qty, round_qty_fn=round_qty_fn)
    if not plan:
        return None
    tier = plan[0]
    if abs(reduced_qty - float(tier["qty"])) <= tol:
        return float(tier["tier_pct"])
    return None


class AdverseRadarMixin:
    """
    Dual-track VPS defense:
    - 开仓: 10% 硬止损全平（挂一次，实盘核实）
    - 朝 TP1: 达雷达激活比例 → 撤硬止损 + 雷达保本移动止损
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
        if not hasattr(self, "adverse_arm_dingtalk_sent"):
            self.adverse_arm_dingtalk_sent = False

    def _reset_adverse_radar(self) -> None:
        self.adverse_sl_armed = False
        self.adverse_sl_prices = []
        self.adverse_consumed_tiers = []
        self._adverse_last_repair_ts = 0.0
        self.adverse_arm_dingtalk_sent = False

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

    def _radar_activation_reached(self, curr_px: float) -> bool:
        """True when price has reached the TP1-distance radar activation threshold."""
        progress = (
            self._radar_activation_progress(curr_px)
            if hasattr(self, "_radar_activation_progress")
            else 0.0
        )
        if progress >= 1.0:
            return True
        if hasattr(self, "_is_radar_active") and self._is_radar_active():
            return True
        return False

    def _has_live_adverse_shield(self) -> bool:
        """Exchange-first: any 10% hard stop still on book or marked armed."""
        self._init_adverse_radar_fields()
        if self._collect_adverse_stop_orders():
            return True
        return bool(self.adverse_sl_armed or self.adverse_sl_prices)

    def _should_disarm_adverse_for_recovery(self, curr_px: float) -> bool:
        """
        Cancel 10% hard stop when radar should take over:
        - TP1 activation distance reached (progress 100%)
        - radar breakeven already active (SL past entry)
        """
        if not self._radar_activation_reached(curr_px):
            return False
        return self._has_live_adverse_shield()

    def _disarm_shield_before_radar(
        self,
        curr_px: float,
        *,
        reason: str = "radar_tp1_activation",
        notify: bool = False,
    ) -> dict[str, Any]:
        """Mandatory pre-radar step: cancel 10% hard stop (never touches TP123)."""
        if not self._radar_activation_reached(curr_px):
            return {"cancelled": 0, "skipped": "radar_not_active", "reason": reason}
        if not self._has_live_adverse_shield():
            return {"cancelled": 0, "skipped": "no_shield", "reason": reason}
        return self._disarm_adverse_staged_stops(reason=reason, notify=notify)

    def _handoff_shield_to_radar(self, live_qty: float, curr_px: float) -> bool:
        """After shield disarm: activate radar breakeven trail when TP1 distance is met."""
        if curr_px <= 0:
            return False
        progress = (
            self._radar_activation_progress(curr_px)
            if hasattr(self, "_radar_activation_progress")
            else 0.0
        )
        if progress < 1.0 and not (hasattr(self, "_is_radar_active") and self._is_radar_active()):
            return False
        live_qty = self._resolve_adverse_live_qty(live_qty)
        if hasattr(self, "_refresh_radar_state_on_recover"):
            self._refresh_radar_state_on_recover(curr_px, float(self.watched_entry or 0))
        if hasattr(self, "_process_radar_trailing"):
            return bool(self._process_radar_trailing(live_qty, curr_px))
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

    def _place_adverse_stop_slice(self, stop_price: float, qty: float) -> bool:
        """Place 10% hard stop — prefer stop-market full close."""
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

        if hasattr(client, "place_stop_market_order"):
            # Full-position 10% hard stop — closePosition avoids origQty=0 verify false negatives.
            order = client.place_stop_market_order(
                close_side, stop_price, symbol, quantity=None,
            )
            if order:
                return True
        limit_px = round_price(stop_price)
        if hasattr(client, "place_stop_limit_order"):
            order = client.place_stop_limit_order(
                close_side, stop_price, limit_px, symbol, quantity=qty, reduce_only=True,
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
            "10%硬止损未对齐",
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
        """Restart: read live stops first, purge duplicates, never blind re-arm."""
        self._init_adverse_radar_fields()
        self._adverse_last_repair_ts = time.time()
        audit = self._sync_adverse_shield_from_exchange(live_qty)
        plan = audit.get("plan") or []
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
        self._adverse_last_repair_ts = time.time()
        self.adverse_arm_dingtalk_sent = False

        result = {"cancelled": n, "reason": reason, "had_open": len(open_before)}
        if n > 0:
            logger.info(
                "[User %s] adverse SL disarmed (%s), cancelled %s stops",
                self.user_id, reason, n,
            )
        if notify and (n > 0 or open_before):
            entry = float(self.watched_entry or 0)
            stop_px = adverse_hard_stop_price(entry, str(self.current_side or "LONG"))
            msg = (
                f"雷达接管 · {reason} | 已撤 10% 硬止损 {n} 笔"
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
        if hasattr(self, "_save_state"):
            self._save_state()
        return result

    def _arm_adverse_shield_at_open(self, live_qty: float) -> dict[str, Any]:
        """开仓后挂一次 10% 硬止损（交易所优先，已存在则跳过）。"""
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
            msg = (
                f"10% 硬止损已挂 | 开仓价 {detail['entry']:.2f} → 止损 @{stop_px:.2f} | "
                f"全平 {detail['live_qty']}"
            )
            self._log("ADVERSE_SL", msg, detail)
            self._alert("warning", "ADVERSE_SL", "防护盾 · 10%硬止损", msg, detail)
            self.adverse_arm_dingtalk_sent = True
        elif repair and placed > 0:
            msg = f"10% 硬止损补挂 | @{detail['stop_price']:.2f} qty={detail['live_qty']}"
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
        Dual-track defense (exchange-first):
        - 朝 TP1 达雷达激活 → 先撤 10% 硬止损，再挂雷达保本移动止损
        - 雷达未激活 → 静默维护 10% 硬止损（缺失才补挂）
        """
        if curr_px <= 0:
            return

        live_qty = self._resolve_adverse_live_qty(live_qty)
        progress = self._radar_activation_progress(curr_px) if hasattr(self, "_radar_activation_progress") else 0.0

        if self._radar_activation_reached(curr_px):
            disarm = self._disarm_shield_before_radar(
                curr_px, reason="radar_tp1_activation", notify=True,
            )
            if disarm.get("cancelled", 0) > 0:
                self._log(
                    "RECOVERY",
                    f"雷达激活 · 10%硬止损已撤，保本移动止损启动 | 现价 {curr_px:.2f} | 进度 {progress:.0%}",
                    {
                        "entry": self.watched_entry,
                        "price": curr_px,
                        "side": self.current_side,
                        "progress": progress,
                        "disarm": disarm,
                    },
                )
            if hasattr(self, "_process_radar_trailing"):
                self._process_radar_trailing(live_qty, curr_px)
            elif self._handoff_shield_to_radar(live_qty, curr_px):
                pass
            return

        self._process_adverse_radar_guard(live_qty, curr_px)

        if progress >= 0.5 and getattr(self, "_scan_ticks", 0) % 5 == 0:
            logger.info(
                "[User %s] 📡 雷达预热: 进度 %.0f%% | 现价 %.2f | 10%%硬止损守护中",
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
                reason=f"10%硬止损触发 · {cause}",
            )
            result.update({
                "defense": tp_result,
                "action_msg": f"10%硬止损全平 · {cause}",
            })
            self._alert(
                "critical",
                "ADVERSE_SL_HIT",
                "防护盾触发 · 10%硬止损",
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
