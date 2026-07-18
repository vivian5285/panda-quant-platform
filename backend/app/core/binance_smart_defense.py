"""Legacy Binance smart defense stack — shared Gemini TP/radar reconcile for all USDT-M supervisors."""

import logging
import time

from app.core.symbol_precision import round_price
from app.core.tp_slice_guard import compute_tp_slices, infer_filled_tp_levels, slices_to_level_dicts
from app.core.tp_regime_ratios import enrich_tp_alert_detail
from app.core.tp_orphan_guard import (
    format_obsolete_tp_detail,
    tp_levels_obsolete_by_radar,
)
from app.core.tp_defense_reconcile import (
    STARTUP_ORDER_FETCH_DELAY,
    STARTUP_ORDER_FETCH_RETRIES,
    TP_PRICE_MATCH_TOL,
    dedupe_orders_by_id,
    pick_best_tp_order,
    tp_price_matches,
    tp_qty_matches,
    tp_qty_tolerance,
)

logger = logging.getLogger(__name__)


class BinanceSmartDefenseMixin:
    """Gemini shared TP/radar defense stack — Binance, OKX, Gate via PositionSupervisor."""

    user_id: int
    client: object
    symbol: str
    current_side: str | None
    tv_tps: list
    regime: int
    regime_settings: dict
    watched_qty: float
    watched_entry: float
    current_sl: float

    def _def_log(self, msg: str, level: int = logging.INFO) -> None:
        logger.log(level, f"[User {self.user_id}] {msg}")

    def _split_tp_quantities(self, qty: float, ratios: list) -> tuple:
        """余数吸收：qty1+qty2+qty3 == qty"""
        qty1 = round(qty * ratios[0], 3)
        qty2 = round(qty * ratios[1], 3)
        qty3 = round(qty - qty1 - qty2, 3)
        return qty1, qty2, qty3

    def _consumed_tp_level_set(self) -> set[int]:
        return {int(x) for x in (getattr(self, "consumed_tp_levels", []) or []) if int(x) in (1, 2, 3)}

    def _current_tp_price(self) -> float:
        if hasattr(self.client, "get_current_price"):
            try:
                return float(self.client.get_current_price(self.symbol) or 0)
            except Exception:
                return 0.0
        return 0.0

    def _tp_exclude_levels(self, live_qty: float, curr_px: float | None = None) -> set[int]:
        from app.core.tp_slice_guard import should_skip_rehang_tp_level

        px = float(curr_px or 0) if curr_px else self._current_tp_price()
        if hasattr(self, "_sync_consumed_tp_levels"):
            self._sync_consumed_tp_levels(live_qty, px)
        exclude = self._consumed_tp_level_set()
        if hasattr(self, "_active_tp_exclude_levels") and px > 0:
            exclude |= self._active_tp_exclude_levels(live_qty, px)
        # Hard exclude any tier that would instant-fill or qty+book implies filled
        open_prices = []
        if hasattr(self, "_open_tp_prices_on_book"):
            open_prices = self._open_tp_prices_on_book()
        elif hasattr(self, "_collect_tp_limit_orders"):
            open_prices = [float(o.get("price", 0) or 0) for o in self._collect_tp_limit_orders()]
        for i, tp_px in enumerate(list(getattr(self, "tv_tps", []) or [])[:3]):
            level = i + 1
            if level in exclude:
                continue
            skip, _reason = should_skip_rehang_tp_level(
                level,
                float(tp_px or 0),
                side=getattr(self, "current_side", None),
                curr_px=px,
                consumed=exclude,
                live_qty=float(live_qty or 0),
                initial_qty=float(getattr(self, "initial_qty", 0) or live_qty or 0),
                regime=int(getattr(self, "regime", 3) or 3),
                tv_tps=list(getattr(self, "tv_tps", []) or []),
                regime_settings=getattr(self, "regime_settings", {}) or {},
                open_tp_prices=open_prices,
                is_contracts=str(getattr(self, "exchange_id", "")).lower() == "deepcoin",
                peak_px=float(getattr(self, "best_price", 0) or 0),
            )
            if skip:
                exclude.add(level)
        return exclude

    def _active_tp_level_dicts(self, live_qty: float, curr_px: float | None = None) -> list[dict]:
        live_qty = self._resolve_live_qty(live_qty)
        exclude = self._tp_exclude_levels(live_qty, curr_px)
        if hasattr(self, "_compute_tp_slices"):
            slices = self._compute_tp_slices(live_qty, exclude_levels=exclude)
        else:
            slices = compute_tp_slices(
                live_qty,
                self.regime,
                self.tv_tps,
                self.regime_settings,
                exclude_levels=exclude,
            )
        return slices_to_level_dicts(slices)

    def _cancel_tp_orders_for_consumed_levels(self) -> int:
        """Remove stale TP orders at tiers already eaten (e.g. TP1 after partial fill)."""
        consumed = self._consumed_tp_level_set()
        if not consumed:
            return 0
        cancelled = 0
        for level in sorted(consumed):
            idx = level - 1
            if idx < 0 or idx >= len(self.tv_tps):
                continue
            px = float(self.tv_tps[idx])
            if px <= 0:
                continue
            for o in self._collect_tp_limit_orders():
                if not tp_price_matches(o["price"], px):
                    continue
                oid = o.get("orderId")
                if oid:
                    self.client.cancel_order(self.symbol, int(oid))
                    cancelled += 1
                    time.sleep(0.2)
        if cancelled:
            self._def_log(f"🧹 已撤销已成交档位多余止盈 {cancelled} 张 (consumed={sorted(consumed)})")
        return cancelled

    def _cancel_tp_orders_at_levels(self, levels: list[int]) -> int:
        """Cancel open TP limits at specific tier numbers (1=TP1, 2=TP2, ...)."""
        if not levels:
            return 0
        cancelled = 0
        targets = set(int(x) for x in levels if int(x) in (1, 2, 3))
        for level in sorted(targets):
            idx = level - 1
            if idx < 0 or idx >= len(self.tv_tps):
                continue
            px = float(self.tv_tps[idx])
            if px <= 0:
                continue
            for o in self._collect_tp_limit_orders():
                if not tp_price_matches(o["price"], px):
                    continue
                oid = o.get("orderId")
                if oid:
                    self.client.cancel_order(self.symbol, int(oid))
                    cancelled += 1
                    time.sleep(0.2)
        return cancelled

    def _cancel_obsolete_tp_after_radar_move(self, radar_sl: float) -> dict:
        """
        After radar SL advances past TP1/TP2, stale limit TPs are useless — cancel them.
        Prevents orphan limits from filling into reverse exposure after flat.
        """
        side = getattr(self, "current_side", None)
        obsolete = tp_levels_obsolete_by_radar(
            radar_sl,
            side,
            list(getattr(self, "tv_tps", []) or []),
            consumed_levels=list(getattr(self, "consumed_tp_levels", []) or []),
            max_level=2,
        )
        detail = format_obsolete_tp_detail(
            obsolete, radar_sl, list(getattr(self, "tv_tps", []) or []), side,
        )
        detail["cancelled"] = 0
        if not obsolete:
            return detail
        detail["cancelled"] = self._cancel_tp_orders_at_levels(obsolete)
        if detail["cancelled"] > 0:
            self._def_log(
                f"🧹 雷达越过 TP{obsolete} → 撤销过时限价止盈 {detail['cancelled']} 张 @ SL {radar_sl:.2f}",
            )
            if hasattr(self, "_log"):
                self._log(
                    "TP_ORPHAN_PURGE",
                    f"雷达止损 {radar_sl:.2f} 已越过 TP{obsolete}，撤销 {detail['cancelled']} 张",
                    detail,
                )
            if hasattr(self, "_alert"):
                self._alert(
                    "warning",
                    "TP_ORPHAN_PURGE",
                    "雷达越过止盈 · 撤销过时 TP",
                    f"SL {radar_sl:.2f} ≥ TP{obsolete}，已撤 {detail['cancelled']} 张限价单",
                    detail,
                )
        return detail

    def _resolve_live_qty(self, fallback_qty: float) -> float:
        pos = self._get_active_position()
        if pos and pos["size"] > 0:
            live = round(pos["size"], 3)
            if abs(live - fallback_qty) > 0.001:
                self._def_log(f"📐 实盘数量校正: 账本 {fallback_qty} → 交易所 {live} ETH")
            return live
        return fallback_qty

    def _wait_verify(self, checks_fn, retries: int = 3, delay: float = 0.6):
        for _ in range(retries):
            result = checks_fn()
            if result:
                return result
            time.sleep(delay)
        return checks_fn()

    def _flat_purge_side_snapshot(self) -> str | None:
        snap = getattr(self, "_flat_purge_side", None)
        if snap in ("LONG", "SHORT"):
            return snap
        side = getattr(self, "current_side", None)
        return side if side in ("LONG", "SHORT") else None

    def _is_flat_orphan_tp_order(self, o: dict, side: str | None = None) -> bool:
        """Identify TP123 limits to cancel after flat — works even if current_side was cleared."""
        if o.get("type") != "LIMIT":
            return False
        val = o.get("reduceOnly")
        if val is True or str(val).lower() in ("true", "1"):
            return True
        side = side or self._flat_purge_side_snapshot()
        if not side:
            return False
        close_side = "BUY" if side == "SHORT" else "SELL"
        if o.get("side") != close_side:
            return False
        px = float(o.get("price", 0) or 0)
        if px <= 0:
            return False
        tv_tps = list(getattr(self, "tv_tps", []) or [])
        if tv_tps:
            return any(tp_price_matches(px, t) for t in tv_tps if t > 0)
        return True

    def _is_tp_limit_order(self, o: dict) -> bool:
        # VPS hard SL resting limit must not be counted as TP / orphan
        if hasattr(self, "_is_hard_sl_limit_order") and self._is_hard_sl_limit_order(o):
            return False
        if o.get("type") != "LIMIT":
            return False
        val = o.get("reduceOnly")
        if val is True or str(val).lower() in ("true", "1"):
            return True
        if not self.current_side:
            return False
        close_side = "BUY" if self.current_side == "SHORT" else "SELL"
        if o.get("side") != close_side:
            return False
        px = float(o.get("price", 0) or 0)
        if px <= 0:
            return False
        return any(tp_price_matches(px, t) for t in self.tv_tps if t > 0)

    def _tp_price_tol(self) -> float:
        return TP_PRICE_MATCH_TOL

    def _tp_qty_tol(self, expected: float, anchor: float) -> float:
        return tp_qty_tolerance(expected, anchor, is_contracts=False)

    def _collect_limit_tp_prices(self) -> list[float]:
        prices: list[float] = []
        for o in self.client.get_open_orders(self.symbol) or []:
            if not self._is_tp_limit_order(o):
                continue
            px = float(o.get("price", 0) or 0)
            if px > 0:
                prices.append(round(px, 2))
        return sorted(prices)

    def _collect_tp_limit_orders(self) -> list[dict]:
        orders = []
        for o in self.client.get_open_orders(self.symbol) or []:
            if not self._is_tp_limit_order(o):
                continue
            px = float(o.get("price", 0) or 0)
            if px <= 0:
                continue
            orders.append({
                "orderId": o.get("orderId"),
                "price": round_price(px),
                "qty": round(float(o.get("origQty", o.get("quantity", 0)) or 0), 3),
            })
        return dedupe_orders_by_id(orders)

    def _expected_tp_count(self, tp_pxs=None) -> int:
        live_qty = float(getattr(self, "watched_qty", 0) or 0)
        if live_qty <= 0:
            tp_pxs = tp_pxs if tp_pxs is not None else self.tv_tps
            return sum(1 for t in tp_pxs if t > 0)
        return len(self._active_tp_level_dicts(live_qty))

    def _expected_tp_levels(self, live_qty: float, curr_px: float | None = None) -> list[dict]:
        return self._active_tp_level_dicts(live_qty, curr_px)

    def _audit_tp_levels(
        self,
        live_qty: float,
        tolerance: float | None = None,
        qty_tol: float | None = None,
        curr_px: float | None = None,
    ) -> dict:
        live_qty = self._resolve_live_qty(live_qty)
        price_tol = self._tp_price_tol() if tolerance is None else float(tolerance)
        orders = self._collect_tp_limit_orders()
        levels = []
        matched_full = 0
        issues = []
        consumed = sorted(self._consumed_tp_level_set())

        for lv in self._expected_tp_levels(live_qty, curr_px):
            if lv["qty"] <= 0 or lv["price"] <= 0:
                continue
            at_px = [o for o in orders if tp_price_matches(o["price"], lv["price"], price_tol)]
            q_tol = (
                self._tp_qty_tol(lv["qty"], live_qty)
                if qty_tol is None
                else float(qty_tol)
            )
            status = "ok"
            actual_qty = 0.0
            if len(at_px) == 0:
                status = "missing"
                issues.append(f"TP{lv['level']} @{lv['price']:.2f} 缺失")
            elif len(at_px) > 1:
                status = "duplicate"
                actual_qty = sum(o["qty"] for o in at_px)
                issues.append(f"TP{lv['level']} @{lv['price']:.2f} 重复 {len(at_px)} 张")
            elif not tp_qty_matches(lv["qty"], at_px[0]["qty"], live_qty):
                status = "qty_mismatch"
                actual_qty = at_px[0]["qty"]
                issues.append(
                    f"TP{lv['level']} 数量 {actual_qty} ≠ 期望 {lv['qty']} "
                    f"(容差 {q_tol:.4f}, {self.regime_settings[self.regime]['ratios']})"
                )
            else:
                matched_full += 1
                actual_qty = at_px[0]["qty"]
            levels.append({**lv, "status": status, "actual_qty": actual_qty})

        expected_prices = [lv["price"] for lv in levels]
        orphans = [
            o for o in orders
            if not any(tp_price_matches(o["price"], p, price_tol) for p in expected_prices)
        ]
        for o in orphans:
            issues.append(f"孤儿止盈 @{o['price']:.2f} qty={o['qty']}")

        expected = len(levels)
        pending_prices = sorted({o["price"] for o in orders})
        return {
            "matched_full": matched_full,
            "expected": expected,
            "levels": levels,
            "issues": issues,
            "orphans": orphans,
            "pending_prices": pending_prices,
            "live_qty": live_qty,
            "consumed_tp_levels": consumed,
        }

    def _format_audit_summary(self, audit: dict) -> str:
        parts = []
        consumed = audit.get("consumed_tp_levels") or []
        live_qty = float(audit.get("live_qty") or getattr(self, "watched_qty", 0) or 0)
        if consumed:
            pending = [lv for lv in audit.get("levels", []) if lv.get("level") not in consumed]
            rem_qty = round(sum(float(lv.get("qty") or 0) for lv in pending), 3)
            parts.append(
                f"已成交TP{''.join(str(x) for x in consumed)}"
                f" → 挂剩余{len(pending)}档/{rem_qty}ETH"
            )
        initial = float(getattr(self, "initial_qty", 0) or 0)
        if initial > live_qty > 0:
            parts.append(f"初始{initial}→现仓{live_qty}")
        for lv in audit.get("levels", []):
            if lv["price"] <= 0:
                continue
            icon = "✅" if lv["status"] == "ok" else "❌"
            line = f"{icon}TP{lv['level']} {lv['qty']}@{lv['price']:.2f}"
            if lv["status"] != "ok":
                line += f"({lv['status']})"
            parts.append(line)
        if audit.get("issues"):
            parts.append("问题:" + "; ".join(audit["issues"][:3]))
        return " | ".join(parts) if parts else "无有效 TP"

    def _count_matched_tp_orders(self, tp_pxs, tolerance: float | None = None, live_qty=None):
        tol = self._tp_price_tol() if tolerance is None else float(tolerance)
        if live_qty is not None and live_qty > 0:
            audit = self._audit_tp_levels(live_qty, tolerance=tol)
            return audit["matched_full"], audit["pending_prices"]
        pending_prices = self._collect_limit_tp_prices()
        matched = 0
        for tp in tp_pxs:
            if tp <= 0:
                continue
            if any(tp_price_matches(p, tp, tol) for p in pending_prices):
                matched += 1
        return matched, pending_prices

    def _cancel_orphan_tp_orders(self, live_qty: float, tolerance: float | None = None) -> int:
        tol = self._tp_price_tol() if tolerance is None else float(tolerance)
        audit = self._audit_tp_levels(live_qty, tolerance=tol)
        cancelled = 0
        for o in audit["orphans"]:
            oid = o.get("orderId")
            if oid:
                self.client.cancel_order(self.symbol, int(oid))
                cancelled += 1
                time.sleep(0.2)
        if cancelled:
            self._def_log(f"🧹 撤销 {cancelled} 张孤儿止盈单")
        return cancelled

    def _cancel_stop_orders(self) -> int:
        cancelled = 0
        for o in self.client.get_open_orders(self.symbol) or []:
            if o.get("type") not in ("STOP_MARKET", "STOP"):
                continue
            oid = o.get("orderId")
            if oid:
                self.client.cancel_order(self.symbol, int(oid))
                cancelled += 1
                time.sleep(0.2)
        return cancelled

    def _is_radar_active(self) -> bool:
        if not self.watched_entry or not self.current_sl:
            return False
        if self.current_side == "LONG":
            return self.current_sl > self.watched_entry
        if self.current_side == "SHORT":
            return self.current_sl < self.watched_entry
        return False

    def _radar_sl_to_pass(self):
        return self.current_sl if self._is_radar_active() else None

    def _has_stop_sl_near(self, sl_price: float, tolerance: float = 2.0) -> bool:
        target = round(float(sl_price), 2)
        for o in self.client.get_open_orders(self.symbol) or []:
            otype = str(o.get("type") or o.get("orderType") or "").upper()
            is_stop = otype in ("STOP_MARKET", "STOP") or (
                o.get("isAlgoOrder") and self._order_stop_price(o) > 0
            )
            # Resting hard-SL limit (基础单)
            if (
                not is_stop
                and otype == "LIMIT"
                and hasattr(self, "_is_hard_sl_limit_order")
                and self._is_hard_sl_limit_order(o)
            ):
                try:
                    if abs(round(float(o.get("price") or 0), 2) - target) <= tolerance:
                        return True
                except (TypeError, ValueError):
                    pass
                continue
            if not is_stop:
                continue
            for key in ("stopPrice", "triggerPrice", "activatePrice"):
                val = o.get(key)
                if val is None or str(val).strip() in ("", "0"):
                    continue
                try:
                    if abs(round(float(val), 2) - target) <= tolerance:
                        return True
                except (TypeError, ValueError):
                    continue
        if hasattr(self, "_collect_adverse_stop_orders"):
            from app.core.adverse_radar_guard import _adverse_defense_price
            for o in self._collect_adverse_stop_orders() or []:
                px = _adverse_defense_price(o)
                if px > 0 and abs(px - target) <= tolerance:
                    return True
        return False

    def _order_stop_price(self, o: dict) -> float:
        from app.core.adverse_radar_guard import _order_stop_price
        return _order_stop_price(o)

    def _has_duplicate_tp_orders(self, tolerance: float | None = None) -> bool:
        tol = self._tp_price_tol() if tolerance is None else float(tolerance)
        orders = self._collect_tp_limit_orders()
        expected = self._expected_tp_count()
        if expected <= 0:
            return False
        if len(orders) > expected:
            return True
        for tp in self.tv_tps:
            if tp <= 0:
                continue
            at_px = [o for o in orders if tp_price_matches(o["price"], tp, tol)]
            if len(at_px) > 1:
                return True
        return False

    def _defenses_fully_ok(
        self,
        live_qty: float,
        dynamic_sl=None,
        tolerance: float | None = None,
        qty_tol: float | None = None,
        curr_px: float | None = None,
        *,
        require_sl: bool = True,
    ) -> bool:
        price_tol = self._tp_price_tol() if tolerance is None else float(tolerance)
        if require_sl and dynamic_sl is None and hasattr(self, "_radar_sl_to_pass"):
            dynamic_sl = self._radar_sl_to_pass()
        expected_levels = self._expected_tp_levels(live_qty, curr_px)
        if not expected_levels:
            if not require_sl:
                return True
            return dynamic_sl is None or self._has_stop_sl_near(dynamic_sl, price_tol)

        orders = self._collect_tp_limit_orders()
        matched_levels = 0
        expected_prices = []
        for lv in expected_levels:
            q, px = lv["qty"], lv["price"]
            if q <= 0 or px <= 0:
                continue
            expected_prices.append(px)
            at_px = [o for o in orders if tp_price_matches(o["price"], px, price_tol)]
            if len(at_px) != 1:
                return False
            q_tol = self._tp_qty_tol(q, live_qty) if qty_tol is None else float(qty_tol)
            if not tp_qty_matches(q, at_px[0]["qty"], live_qty):
                return False
            matched_levels += 1

        if matched_levels < len(expected_levels):
            return False

        for o in orders:
            if not any(tp_price_matches(o["price"], p, price_tol) for p in expected_prices):
                return False

        if require_sl and dynamic_sl and not self._has_stop_sl_near(dynamic_sl, price_tol):
            return False
        return True

    def _order_stop_price(self, o: dict) -> float:
        for key in ("stopPrice", "triggerPrice", "activatePrice"):
            val = o.get(key)
            if val is None or str(val).strip() in ("", "0"):
                continue
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
        return 0.0

    def _cancel_radar_stop_orders(self, tolerance: float = 2.0) -> int:
        """Cancel breakeven/radar STOP orders only — never touch TP limits or 10% adverse shield."""
        adverse_prices: set[float] = set()
        if hasattr(self, "_adverse_tier_stop_prices"):
            try:
                adverse_prices = set(self._adverse_tier_stop_prices())
            except Exception:
                adverse_prices = set()
        cancelled = 0
        for o in self.client.get_open_orders(self.symbol) or []:
            if o.get("type") not in ("STOP_MARKET", "STOP"):
                continue
            stop_px = self._order_stop_price(o)
            if adverse_prices and any(abs(stop_px - t) <= tolerance for t in adverse_prices):
                continue
            oid = o.get("orderId")
            if oid:
                self.client.cancel_order(self.symbol, int(oid))
                cancelled += 1
                time.sleep(0.2)
        return cancelled

    def _purge_duplicate_tp_orders(self, live_qty: float) -> int:
        """Cancel extra TP at same tier; keep best qty match (exchange-first)."""
        live_qty = self._resolve_live_qty(live_qty)
        cancelled = 0
        for lv in self._expected_tp_levels(live_qty):
            if lv["qty"] <= 0 or lv["price"] <= 0:
                continue
            orders = self._collect_tp_limit_orders()
            at_px = [o for o in orders if tp_price_matches(o["price"], lv["price"])]
            if len(at_px) <= 1:
                continue
            keep = pick_best_tp_order(at_px, lv["qty"])
            keep_id = keep.get("orderId") if keep else None
            for o in at_px:
                oid = o.get("orderId")
                if oid is None or oid == keep_id:
                    continue
                self.client.cancel_order(self.symbol, int(oid))
                cancelled += 1
                time.sleep(0.2)
        if cancelled:
            self._def_log(f"🧹 去重撤销多余止盈 {cancelled} 张（保留最优张数）")
        return cancelled

    def _patch_missing_tp_levels(
        self, live_qty: float, tolerance: float | None = None, qty_tol: float | None = None,
        curr_px: float | None = None,
    ) -> int:
        from app.core.tp_slice_guard import should_skip_rehang_tp_level

        price_tol = self._tp_price_tol() if tolerance is None else float(tolerance)
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        live_qty = self._resolve_live_qty(live_qty)
        px_now = float(curr_px or 0) or self._current_tp_price()
        if hasattr(self, "_sync_consumed_tp_levels"):
            self._sync_consumed_tp_levels(live_qty, px_now)
        self._cancel_tp_orders_for_consumed_levels()
        levels = self._expected_tp_levels(live_qty, px_now)
        placed = 0
        skipped = 0
        open_prices = (
            self._open_tp_prices_on_book()
            if hasattr(self, "_open_tp_prices_on_book")
            else [float(o.get("price", 0) or 0) for o in self._collect_tp_limit_orders()]
        )
        consumed = self._consumed_tp_level_set()

        for lv in levels:
            q, px = lv["qty"], lv["price"]
            level = int(lv.get("level") or 0)
            if q <= 0 or px <= 0:
                continue
            skip, skip_reason = should_skip_rehang_tp_level(
                level or 0,
                px,
                side=self.current_side,
                curr_px=px_now,
                consumed=consumed,
                live_qty=live_qty,
                initial_qty=float(getattr(self, "initial_qty", 0) or live_qty),
                regime=int(getattr(self, "regime", 3) or 3),
                tv_tps=list(getattr(self, "tv_tps", []) or []),
                regime_settings=getattr(self, "regime_settings", {}) or {},
                open_tp_prices=open_prices,
                is_contracts=str(getattr(self, "exchange_id", "")).lower() == "deepcoin",
                peak_px=float(getattr(self, "best_price", 0) or 0),
            )
            if skip:
                skipped += 1
                self._def_log(
                    f"  ⏭ 跳过补挂 TP{level or '?'} @ {px:.2f}（{skip_reason}·防死亡螺旋）",
                    logging.WARNING,
                )
                if level and level not in consumed:
                    consumed.add(level)
                    if hasattr(self, "consumed_tp_levels"):
                        merged = sorted(consumed)
                        if merged != sorted(getattr(self, "consumed_tp_levels", []) or []):
                            self.consumed_tp_levels = merged
                            if hasattr(self, "_save_state"):
                                self._save_state()
                            if hasattr(self, "_alert"):
                                self._alert(
                                    "warning",
                                    "TP_SKIP_REHANG",
                                    f"止盈已成交·拒绝补挂TP{level}",
                                    f"原因={skip_reason} | 现价{px_now:.2f} | 实盘{live_qty} | "
                                    f"已消费{merged} — 若再挂会在TP附近秒成",
                                    {
                                        "level": level,
                                        "tp_price": px,
                                        "skip_reason": skip_reason,
                                        "curr_px": px_now,
                                        "live_qty": live_qty,
                                        "consumed_tp_levels": merged,
                                        "exchange": getattr(self, "exchange_id", None),
                                    },
                                )
                continue
            orders = self._collect_tp_limit_orders()
            at_px = [o for o in orders if tp_price_matches(o["price"], px, price_tol)]
            if len(at_px) == 1 and tp_qty_matches(q, at_px[0]["qty"], live_qty):
                self._def_log(f"  ✓ TP @ {px:.2f} 已存在 {at_px[0]['qty']} ETH，跳过")
                continue
            if len(at_px) > 1:
                self._purge_duplicate_tp_orders(live_qty)
                orders = self._collect_tp_limit_orders()
                at_px = [o for o in orders if tp_price_matches(o["price"], px, price_tol)]
                if len(at_px) == 1 and tp_qty_matches(q, at_px[0]["qty"], live_qty):
                    continue
            for o in at_px:
                oid = o.get("orderId")
                if oid:
                    self.client.cancel_order(self.symbol, int(oid))
                    time.sleep(0.25)
            self._def_log(f"  + 补挂 TP @ {px:.2f} qty={q} ETH")
            if self.client.place_limit_order(
                close_side, q, px, symbol=self.symbol, reduce_only=True
            ):
                placed += 1
            time.sleep(0.4)
        if skipped and hasattr(self, "_log"):
            self._log(
                "TP_SKIP_REHANG",
                f"跳过 {skipped} 档已成交/已达价止盈补挂，实际补挂 {placed}",
                {"skipped": skipped, "placed": placed, "consumed": sorted(consumed)},
            )
        return placed

    def _audit_requires_nuclear(self, audit: dict) -> bool:
        expected = audit.get("expected", 0)
        if expected <= 0:
            return False
        if audit.get("matched_full", 0) >= expected and not audit.get("orphans"):
            return False
        if any(lv.get("status") == "duplicate" for lv in audit.get("levels", [])):
            return False
        # After TP fills, "all missing" is normal (only remaining tiers expected).
        # Nuclear rebuild with empty/stale consumed recreates TP1 near mark → death spiral.
        consumed = self._consumed_tp_level_set()
        live_qty = float(audit.get("live_qty") or getattr(self, "watched_qty", 0) or 0)
        initial = float(getattr(self, "initial_qty", 0) or 0)
        if consumed or (initial > 0 and live_qty > 0 and live_qty < initial * 0.92):
            # Prefer incremental patch only — never cancel-all+rehang full TP123
            if audit.get("matched_full", 0) == 0 and audit.get("issues"):
                return False
            missing = sum(1 for lv in audit.get("levels", []) if lv.get("status") == "missing")
            if missing >= 2:
                return False
        orders = self._collect_tp_limit_orders()
        if len(orders) > expected * 2:
            return True
        if audit.get("matched_full", 0) == 0 and audit.get("issues"):
            missing = sum(1 for lv in audit.get("levels", []) if lv.get("status") == "missing")
            if missing >= expected:
                return True
        qty_bad = [
            lv for lv in audit.get("levels", [])
            if lv.get("status") == "qty_mismatch"
        ]
        if len(qty_bad) >= 2:
            return True
        missing = sum(1 for lv in audit.get("levels", []) if lv.get("status") == "missing")
        if missing >= 2:
            return True
        if audit.get("orphans") and audit.get("matched_full", 0) == 0:
            return True
        return False

    def _defense_result_from_audit(
        self,
        audit: dict,
        *,
        skipped: bool = False,
        rebuilt: bool = False,
        nuclear: bool = False,
    ) -> dict:
        summary = self._format_audit_summary(audit)
        expected = audit.get("expected", 0)
        matched = audit.get("matched_full", 0)
        return {
            "matched": matched,
            "expected": expected,
            "pending_prices": audit.get("pending_prices", []),
            "rebuilt": rebuilt,
            "audit": audit,
            "nuclear": nuclear,
            "skipped": skipped,
            "aligned": matched >= expected and expected > 0,
            "healed": rebuilt or nuclear,
            "summary": summary,
            "after_summary": summary,
        }

    def _reconcile_tp_defenses_on_startup(
        self, live_qty: float, entry: float, dynamic_sl=None
    ) -> dict:
        """VPS reboot: trust exchange book — retry fetch, dedupe, patch gaps only."""
        self._def_log("🔄 重启接管：交易所优先对账止盈（不盲目清场）")
        live_qty = self._resolve_live_qty(live_qty)
        curr_px = self._current_tp_price()
        if hasattr(self, "_sync_consumed_tp_levels"):
            self._sync_consumed_tp_levels(live_qty, curr_px)
        self._cancel_tp_orders_for_consumed_levels()
        rebuilt = False

        for attempt in range(STARTUP_ORDER_FETCH_RETRIES):
            audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
            if self._defenses_fully_ok(
                live_qty, dynamic_sl=None, curr_px=curr_px, require_sl=False,
            ):
                self._def_log(
                    f"✅ 重启对账：盘口已齐，跳过补挂 | {self._format_audit_summary(audit)}"
                )
                return self._defense_result_from_audit(audit, skipped=True)

            if self._has_duplicate_tp_orders() or any(
                lv.get("status") == "duplicate" for lv in audit.get("levels", [])
            ):
                if self._purge_duplicate_tp_orders(live_qty):
                    time.sleep(0.5)
                    continue

            if audit.get("orphans"):
                self._cancel_orphan_tp_orders(live_qty)
                time.sleep(0.4)
                continue

            has_gap = any(
                lv.get("status") in ("missing", "qty_mismatch")
                for lv in audit.get("levels", [])
            )
            if has_gap:
                break

            if attempt < STARTUP_ORDER_FETCH_RETRIES - 1:
                self._def_log(
                    f"⏳ 重启对账：挂单列表未稳，重试 {attempt + 1}/{STARTUP_ORDER_FETCH_RETRIES}"
                )
                time.sleep(STARTUP_ORDER_FETCH_DELAY)

        self._cancel_orphan_tp_orders(live_qty)
        placed = self._patch_missing_tp_levels(live_qty, curr_px=curr_px)
        if placed:
            rebuilt = True
        time.sleep(0.6)

        audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
        if self._defenses_fully_ok(
            live_qty, dynamic_sl=None, curr_px=curr_px, require_sl=False,
        ):
            self._def_log(
                f"✅ 重启增量纠偏完成 | {self._format_audit_summary(audit)}"
            )
            return self._defense_result_from_audit(audit, skipped=not rebuilt, rebuilt=rebuilt)

        self._def_log(
            f"⚠️ 重启对账后仍不齐，升级智能对齐 | {self._format_audit_summary(audit)}",
            logging.WARNING,
        )
        return self._smart_realign_defenses(
            live_qty, entry, dynamic_sl=None, reason="重启纠偏升级",
        )

    def _cancel_all_tp_limit_orders(self, *, flat_purge: bool = False) -> int:
        cancelled = 0
        side_snap = self._flat_purge_side_snapshot() if flat_purge else None
        for o in self.client.get_open_orders(self.symbol) or []:
            is_tp = (
                self._is_flat_orphan_tp_order(o, side_snap)
                if flat_purge
                else self._is_tp_limit_order(o)
            )
            if not is_tp:
                continue
            oid = o.get("orderId")
            if oid:
                self.client.cancel_order(self.symbol, int(oid))
                cancelled += 1
                time.sleep(0.15)
        if cancelled:
            label = "平仓孤儿止盈" if flat_purge else "限价止盈"
            self._def_log(f"🧹 已撤销全部{label} {cancelled} 张")
        return cancelled

    def _ensure_radar_sl(self, dynamic_sl, live_qty=None) -> bool:
        """Place radar breakeven STOP — Route A: Binance 合并单槽，Deepcoin 双轨。"""
        if not dynamic_sl:
            return False
        curr_px = self._current_tp_price() if hasattr(self, "_current_tp_price") else 0.0
        latched = bool(getattr(self, "radar_latched", False))
        if (
            not latched
            and hasattr(self, "_radar_activation_reached")
            and not self._radar_activation_reached(curr_px)
        ):
            self._def_log(
                f"⏸️ 雷达未达激活条件（待路径≥85%或TP成交），"
                f"跳过保本 STOP @ {float(dynamic_sl):.2f}",
            )
            return False
        sl = float(dynamic_sl)
        if hasattr(self, "_clamp_radar_sl_to_tv_floor"):
            sl = self._clamp_radar_sl_to_tv_floor(sl)
        curr_px = self._current_tp_price()
        if (
            curr_px > 0
            and hasattr(self, "_mark_price_trusted")
            and self._mark_price_trusted(curr_px)
            and hasattr(self, "_market_safe_stop_price")
        ):
            sl = self._market_safe_stop_price(sl, curr_px)
        elif curr_px > 0 and hasattr(self, "_mark_price_trusted") and self._mark_price_trusted(curr_px):
            from app.core.radar_trail import clamp_stop_market_safe
            sl = clamp_stop_market_safe(sl, curr_px, getattr(self, "current_side", None))
        qty = live_qty if live_qty is not None else getattr(self, "watched_qty", 0)
        if hasattr(self, "_uses_dual_stop_track") and not self._uses_dual_stop_track():
            if hasattr(self, "_sync_binance_merged_stop"):
                result = self._sync_binance_merged_stop(qty, radar_sl=sl, force_replace=True)
                return bool(result.get("aligned") or result.get("armed"))
        if self._has_stop_sl_near(sl):
            return True
        self._cancel_radar_stop_orders()
        time.sleep(0.25)
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        symbol = getattr(self, "symbol", "ETHUSDT")
        res = self.client.place_stop_market_order(
            close_side, sl, symbol, quantity=None,
        )
        if not res:
            self._def_log(
                f"⚠️ 雷达保本 STOP 下单失败 @ {sl:.2f}（closePosition，不与 TP 抢份额）",
                logging.WARNING,
            )
            return False
        time.sleep(0.35)
        on_book = self._has_stop_sl_near(sl)
        if not on_book:
            self._def_log(
                f"⚠️ 雷达 STOP 已提交但盘口未核实 @ {sl:.2f}",
                logging.WARNING,
            )
        return on_book

    def _rebuild_tp_limit_orders(self, qty: float, entry: float, dynamic_sl=None) -> int:
        """Place remaining TP tiers for live qty; skip consumed levels (e.g. TP1 already eaten)."""
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"

        live_qty = self._resolve_live_qty(qty)
        if live_qty <= 0:
            self._def_log(f"重建防线跳过：交易所无可用持仓 (传入 {qty} {getattr(self, 'qty_unit', '')})", logging.WARNING)
            return 0

        if abs(live_qty - qty) > 0.001:
            self.watched_qty = live_qty
            self._save_state()

        from app.core.tp_slice_guard import should_skip_rehang_tp_level

        curr_px = self._current_tp_price()
        if hasattr(self, "_sync_consumed_tp_levels"):
            self._sync_consumed_tp_levels(live_qty, curr_px)
        self._cancel_tp_orders_for_consumed_levels()
        levels = self._expected_tp_levels(live_qty, curr_px)
        placed = 0
        consumed = self._consumed_tp_level_set()
        open_prices = (
            self._open_tp_prices_on_book()
            if hasattr(self, "_open_tp_prices_on_book")
            else [float(o.get("price", 0) or 0) for o in self._collect_tp_limit_orders()]
        )
        level_desc = " ".join(
            f"TP{lv['level']}={lv['qty']}@{lv['price']:.2f}" for lv in levels if lv["qty"] > 0
        )
        self._def_log(
            f"🕸️ 补挂剩余止盈: 持仓 {live_qty} {getattr(self, 'qty_unit', '')}"
            + (f" | 已成交TP{''.join(str(x) for x in sorted(consumed))}" if consumed else "")
            + f" → {level_desc or '无剩余档'}"
        )

        for lv in levels:
            q, px = lv["qty"], lv["price"]
            level = int(lv.get("level") or 0)
            if q <= 0 or px <= 0:
                continue
            skip, skip_reason = should_skip_rehang_tp_level(
                level,
                px,
                side=self.current_side,
                curr_px=curr_px,
                consumed=consumed,
                live_qty=live_qty,
                initial_qty=float(getattr(self, "initial_qty", 0) or live_qty),
                regime=int(getattr(self, "regime", 3) or 3),
                tv_tps=list(getattr(self, "tv_tps", []) or []),
                regime_settings=getattr(self, "regime_settings", {}) or {},
                open_tp_prices=open_prices,
                is_contracts=str(getattr(self, "exchange_id", "")).lower() == "deepcoin",
                peak_px=float(getattr(self, "best_price", 0) or 0),
            )
            if skip:
                self._def_log(
                    f"  ⏭ 重建跳过 TP{level} @ {px:.2f}（{skip_reason}）",
                    logging.WARNING,
                )
                if level and level not in consumed:
                    consumed.add(level)
                    self.consumed_tp_levels = sorted(consumed)
                    if hasattr(self, "_save_state"):
                        self._save_state()
                continue
            res = self.client.place_limit_order(
                close_side, q, px, symbol=self.symbol, reduce_only=True
            )
            if res:
                placed += 1
            time.sleep(0.35)

        return placed

    def _nuclear_realign_tp(self, live_qty: float, entry: float, dynamic_sl=None, rounds: int = 3) -> dict:
        sl_preserve = dynamic_sl is not None
        last_audit = self._audit_tp_levels(live_qty)
        for r in range(rounds):
            self._def_log(
                f"☢️ 核武级止盈清场重挂 {r + 1}/{rounds} | 持仓 {live_qty} {getattr(self, 'qty_unit', '')} | "
                f"当前 {last_audit['matched_full']}/{last_audit['expected']} | "
                f"{self._format_audit_summary(last_audit)}",
                logging.WARNING,
            )
            if sl_preserve:
                self._cancel_all_tp_limit_orders()
            else:
                self.client.cancel_all_open_orders(self.symbol)
            time.sleep(1.0)
            tp_sl = None if sl_preserve else dynamic_sl
            placed = self._rebuild_tp_limit_orders(live_qty, entry, dynamic_sl=tp_sl)
            self._def_log(f"☢️ 核武轮 {r + 1} 新挂 {placed} 笔限价止盈")
            if sl_preserve:
                time.sleep(0.6)
                self._ensure_radar_sl(dynamic_sl, live_qty)
            time.sleep(1.0)
            last_audit = self._audit_tp_levels(live_qty)
            if self._defenses_fully_ok(live_qty, dynamic_sl):
                self._def_log(f"☢️ 核武重挂成功: {self._format_audit_summary(last_audit)}")
                return last_audit
            self._def_log(
                f"☢️ 核武轮 {r + 1} 仍未对齐: {self._format_audit_summary(last_audit)}",
                logging.WARNING,
            )
            time.sleep(1.5)
        return last_audit

    def _wait_tp_hung(self, tp_pxs, live_qty=None, retries: int = 5, delay: float = 0.8):
        expected = self._expected_tp_count(tp_pxs)
        matched, pending = 0, []
        for _ in range(retries):
            if live_qty is not None and live_qty > 0:
                audit = self._audit_tp_levels(live_qty)
                matched = audit["matched_full"]
                pending = audit["pending_prices"]
            else:
                matched, pending = self._count_matched_tp_orders(tp_pxs)
            if expected == 0 or matched >= expected:
                return matched, pending
            time.sleep(delay)
        return matched, pending

    def _ensure_defenses_on_recover(self, live_qty: float, entry: float, dynamic_sl=None):
        """重启/异动接管：审计 → 齐全跳过 → 增量补挂 → 仍失败才清场重建"""
        audit = self._audit_tp_levels(live_qty)
        expected = audit["expected"]
        matched = audit["matched_full"]
        pending_prices = audit["pending_prices"]
        self._def_log(
            f"📊 防线审计: 持仓 {live_qty} ETH | TP {matched}/{expected} | "
            f"{self._format_audit_summary(audit)}"
        )

        if self._has_duplicate_tp_orders():
            self._purge_duplicate_tp_orders(live_qty)
            time.sleep(0.4)
            audit = self._audit_tp_levels(live_qty)
            matched = audit["matched_full"]
            pending_prices = audit["pending_prices"]

        if self._audit_requires_nuclear(audit):
            self._def_log(
                f"☢️ 审计触发核武级重挂: {len(self._collect_tp_limit_orders())} 张止盈 | "
                f"{self._format_audit_summary(audit)}",
                logging.WARNING,
            )
            audit = self._nuclear_realign_tp(live_qty, entry, dynamic_sl=dynamic_sl, rounds=3)
            return audit["matched_full"], audit["pending_prices"], audit["expected"], True

        if self._defenses_fully_ok(live_qty, dynamic_sl, require_sl=False):
            self._def_log(f"✅ TP123 比例齐全 ({matched}/{expected}) @ {pending_prices}，跳过补挂")
            if dynamic_sl:
                self._ensure_radar_sl(dynamic_sl, live_qty)
            return matched, pending_prices, expected, False

        self._cancel_orphan_tp_orders(live_qty)
        self._def_log(f"📋 止盈未齐 ({matched}/{expected})，增量补挂缺失档（保留已有正确单）")
        self._patch_missing_tp_levels(live_qty)
        time.sleep(0.8)
        matched, pending_prices = self._wait_tp_hung(
            self.tv_tps, live_qty=live_qty, retries=5, delay=1.0,
        )
        audit = self._audit_tp_levels(live_qty)
        matched = audit["matched_full"]

        if self._defenses_fully_ok(live_qty, dynamic_sl, require_sl=False):
            self._def_log(f"✅ 增量补挂成功 ({matched}/{expected}) @ {audit['pending_prices']}")
            if dynamic_sl:
                self._ensure_radar_sl(dynamic_sl, live_qty)
            return matched, audit["pending_prices"], expected, True

        self._def_log(
            f"⚠️ 增量补挂仍不足 ({matched}/{expected}) {audit['issues']}，升级核武级重挂",
            logging.WARNING,
        )
        audit = self._nuclear_realign_tp(live_qty, entry, dynamic_sl=dynamic_sl, rounds=3)
        return audit["matched_full"], audit["pending_prices"], expected, True

    def _rebuild_defenses_after_tv_add(
        self,
        live_qty: float,
        entry: float,
        *,
        entry_type: str = "PYRAMID",
        prev_tv_tps: list | None = None,
    ) -> dict:
        """
        加仓后强制重建防线：
        - 按最新 TV tp1/2/3 价格 + 新总头寸重算 regime 分批比例并核武重挂 TP
        - TV 硬止损按新 qty 同步
        - 雷达按新 entry / 新 TP1 距离重算并挂到新总头寸
        """
        entry_type = str(entry_type or "PYRAMID").upper()
        reason = f"{entry_type} 加仓后按新总头寸重挂 TP123/雷达"
        self._def_log(f"🧠 {reason}")
        curr_px = self._current_tp_price()
        side = getattr(self, "current_side", None)
        prev_sl = float(getattr(self, "tv_sl", 0) or 0)

        # 合并硬止损：多头取更低（更宽），空头取更高
        if hasattr(self, "_recompute_vps_hard_sl"):
            sl_meta = self._recompute_vps_hard_sl(entry_px=entry, side=side)
            new_sl = float(getattr(self, "tv_sl", 0) or 0)
            if prev_sl > 0 and new_sl > 0:
                if side == "LONG":
                    self.tv_sl = min(prev_sl, new_sl)
                elif side == "SHORT":
                    self.tv_sl = max(prev_sl, new_sl)
                sl_meta["merged_prev_sl"] = prev_sl
                sl_meta["merged_new_sl"] = new_sl
                sl_meta["stop_price"] = self.tv_sl
                self._vps_hard_sl_meta = sl_meta
                self._def_log(
                    f"📐 加仓合并硬止损: {prev_sl:.2f} + {new_sl:.2f} → {self.tv_sl:.2f} ({side})",
                )

        # 重置雷达追踪器（新加权均价为基准）；未达 TP1 路径比例前 SL=0
        self.best_price = entry
        self.consumed_tp_levels = []
        self.current_sl = 0.0
        if hasattr(self, "radar_latched"):
            self.radar_latched = False
        if hasattr(self, "_radar_path_ok_streak"):
            self._radar_path_ok_streak = 0

        self.watched_qty = live_qty
        self.watched_entry = entry
        self.initial_qty = live_qty

        if hasattr(self, "_refresh_radar_state_on_recover") and curr_px > 0 and entry > 0:
            self._refresh_radar_state_on_recover(curr_px, entry)

        shield: dict = {}
        if float(getattr(self, "tv_sl", 0) or 0) > 0 and hasattr(self, "_sync_tv_hard_stop"):
            shield = self._sync_tv_hard_stop(live_qty, force_replace=True) or {}

        tp_result: dict = {}
        expected_slices: list = []
        if self.tv_tps and any(float(t or 0) > 0 for t in self.tv_tps):
            if hasattr(self, "_sync_consumed_tp_levels"):
                self._sync_consumed_tp_levels(live_qty, curr_px)
            self._cancel_all_tp_limit_orders()
            time.sleep(0.5)
            dynamic_sl = self._radar_sl_to_pass() if hasattr(self, "_radar_sl_to_pass") else None
            tp_result = self._nuclear_realign_tp(
                live_qty, entry, dynamic_sl=dynamic_sl, rounds=3,
            )
            dynamic_sl = self._radar_sl_to_pass() if hasattr(self, "_radar_sl_to_pass") else dynamic_sl
            if dynamic_sl and hasattr(self, "_ensure_radar_sl"):
                tp_result["radar_verified"] = bool(self._ensure_radar_sl(dynamic_sl, live_qty))
            elif hasattr(self, "_uses_dual_stop_track") and not self._uses_dual_stop_track():
                if hasattr(self, "_sync_binance_merged_stop"):
                    radar = (
                        self._effective_radar_sl_for_merge()
                        if hasattr(self, "_effective_radar_sl_for_merge")
                        else None
                    )
                    tp_result["merged_stop"] = self._sync_binance_merged_stop(
                        live_qty, radar_sl=radar, force_replace=True,
                    )
            expected_slices = (
                self._expected_tp_levels(live_qty, curr_px)
                if hasattr(self, "_expected_tp_levels")
                else []
            )

        audit = self._audit_tp_levels(live_qty, curr_px=curr_px) if live_qty > 0 else {}
        result = {
            "reason": reason,
            "entry_type": entry_type,
            "live_qty": live_qty,
            "entry": entry,
            "tv_tps": list(self.tv_tps),
            "prev_tv_tps": list(prev_tv_tps or []),
            "tp_slices": expected_slices,
            "tp_realign": tp_result,
            "shield": shield,
            "radar_sl": getattr(self, "current_sl", None),
            "radar_active": bool(self._is_radar_active()) if hasattr(self, "_is_radar_active") else False,
            "matched": audit.get("matched_full", 0),
            "expected": audit.get("expected", 0),
            "aligned": bool(
                audit.get("expected", 0) > 0
                and audit.get("matched_full", 0) >= audit.get("expected", 0)
            ),
            "summary": self._format_audit_summary(audit) if audit else "",
            "consumed_tp_levels": [],
            "vps_hard_sl_meta": getattr(self, "_vps_hard_sl_meta", None),
            "radar_reset": True,
        }
        if hasattr(self, "_audit_live_exposure"):
            exp = self._audit_live_exposure(live_qty, getattr(self, "current_side", None), curr_px=curr_px)
            result["exposure"] = exp
            if exp.get("over_committed") and not exp.get("side_flip"):
                self._def_log(
                    f"⚠️ 加仓后仍检测到止盈超挂: {exp.get('summary')}",
                    logging.WARNING,
                )
        return enrich_tp_alert_detail(result, regime=self.regime)

    def _smart_realign_defenses(
        self, live_qty: float, entry: float, dynamic_sl=None, reason: str = ""
    ) -> dict:
        """统一智能防线对齐：审计 → 增量或核武 → 仍未达标则强制核武"""
        if reason:
            self._def_log(f"🧠 智能防线对齐: {reason}")
        curr_px = self._current_tp_price()
        if hasattr(self, "_sync_consumed_tp_levels"):
            self._sync_consumed_tp_levels(live_qty, curr_px)
        self._cancel_tp_orders_for_consumed_levels()
        initial = self._audit_tp_levels(live_qty, curr_px=curr_px)
        if self._defenses_fully_ok(
            live_qty, dynamic_sl=None, curr_px=curr_px, require_sl=False,
        ):
            self._def_log(f"✅ 防线已齐，跳过: {self._format_audit_summary(initial)}")
            return {
                "matched": initial["matched_full"],
                "expected": initial["expected"],
                "pending_prices": initial["pending_prices"],
                "rebuilt": False,
                "audit": initial,
                "nuclear": False,
                "skipped": True,
                "aligned": True,
                "summary": self._format_audit_summary(initial),
            }

        if self._has_duplicate_tp_orders():
            self._def_log("🧹 检测到重复止盈，去重保留最优单（不清场）", logging.WARNING)
            self._purge_duplicate_tp_orders(live_qty)
            time.sleep(0.5)
            initial = self._audit_tp_levels(live_qty, curr_px=curr_px)
            if self._defenses_fully_ok(
                live_qty, dynamic_sl=None, curr_px=curr_px, require_sl=False,
            ):
                return self._defense_result_from_audit(initial, skipped=True)

        if self._audit_requires_nuclear(initial):
            self._def_log("🧹 检测到严重错位，清场后重挂", logging.WARNING)
            self._cancel_all_tp_limit_orders()
            time.sleep(0.5)
            initial = self._audit_tp_levels(live_qty)

        self._cancel_orphan_tp_orders(live_qty)
        matched, pending_prices, expected, rebuilt = self._ensure_defenses_on_recover(
            live_qty, entry, dynamic_sl=None,
        )
        audit = self._audit_tp_levels(live_qty)
        nuclear = False

        if expected > 0 and audit["matched_full"] < expected:
            self._def_log(
                f"⚠️ 常规对齐未达标 ({audit['matched_full']}/{expected})，升级核武级清场重挂",
                logging.WARNING,
            )
            audit = self._nuclear_realign_tp(live_qty, entry, dynamic_sl=dynamic_sl, rounds=3)
            matched = audit["matched_full"]
            pending_prices = audit["pending_prices"]
            rebuilt = nuclear = True

        summary = self._format_audit_summary(audit)
        return {
            "matched": matched,
            "expected": expected,
            "pending_prices": pending_prices,
            "rebuilt": rebuilt,
            "audit": audit,
            "nuclear": nuclear,
            "skipped": False,
            "aligned": audit["matched_full"] >= expected and expected > 0,
            "healed": rebuilt or nuclear,
            "summary": summary,
            "after_summary": summary,
        }

    def _realign_radar_defenses(self, live_qty: float, entry: float, new_sl: float) -> bool:
        """雷达推升：Route A 不撤 TV 底线；Binance 合并，Deepcoin 双轨。"""
        curr_px = self._current_tp_price()
        sl = float(new_sl)
        if hasattr(self, "_clamp_radar_sl_to_tv_floor"):
            sl = self._clamp_radar_sl_to_tv_floor(sl)
        if not self._defenses_fully_ok(
            live_qty, dynamic_sl=None, curr_px=curr_px, require_sl=False,
        ):
            if self._audit_requires_nuclear(self._audit_tp_levels(live_qty, curr_px=curr_px)):
                self._nuclear_realign_tp(live_qty, entry, dynamic_sl=new_sl, rounds=2)
            else:
                self._cancel_orphan_tp_orders(live_qty)
                self._patch_missing_tp_levels(live_qty, curr_px=curr_px)
                time.sleep(0.6)
        return self._ensure_radar_sl(sl, live_qty)


SmartDefenseMixin = BinanceSmartDefenseMixin