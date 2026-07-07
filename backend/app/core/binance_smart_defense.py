"""Legacy Binance smart defense stack (_smart_realign_defenses et al.) for multi-user Gemini."""

import logging
import time

from app.core.symbol_precision import round_price
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
    """Port of eth-webhook-server position_supervisor_binance defense audit / realign logic."""

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

    def _is_tp_limit_order(self, o: dict) -> bool:
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
        tp_pxs = tp_pxs if tp_pxs is not None else self.tv_tps
        return sum(1 for t in tp_pxs if t > 0)

    def _expected_tp_levels(self, live_qty: float) -> list[dict]:
        ratios = self.regime_settings[self.regime]["ratios"]
        q1, q2, q3 = self._split_tp_quantities(live_qty, ratios)
        return [
            {"level": 1, "qty": q1, "price": self.tv_tps[0]},
            {"level": 2, "qty": q2, "price": self.tv_tps[1]},
            {"level": 3, "qty": q3, "price": self.tv_tps[2]},
        ]

    def _audit_tp_levels(
        self,
        live_qty: float,
        tolerance: float | None = None,
        qty_tol: float | None = None,
    ) -> dict:
        live_qty = self._resolve_live_qty(live_qty)
        price_tol = self._tp_price_tol() if tolerance is None else float(tolerance)
        orders = self._collect_tp_limit_orders()
        levels = []
        matched_full = 0
        issues = []

        for lv in self._expected_tp_levels(live_qty):
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

        expected = self._expected_tp_count()
        pending_prices = sorted({o["price"] for o in orders})
        return {
            "matched_full": matched_full,
            "expected": expected,
            "levels": levels,
            "issues": issues,
            "orphans": orphans,
            "pending_prices": pending_prices,
            "live_qty": live_qty,
        }

    def _format_audit_summary(self, audit: dict) -> str:
        parts = []
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
            if o.get("type") not in ("STOP_MARKET", "STOP"):
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
        return False

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
    ) -> bool:
        price_tol = self._tp_price_tol() if tolerance is None else float(tolerance)
        tp_pxs = self.tv_tps
        expected = self._expected_tp_count(tp_pxs)
        if expected == 0:
            return dynamic_sl is None or self._has_stop_sl_near(dynamic_sl, price_tol)

        orders = self._collect_tp_limit_orders()
        ratios = self.regime_settings[self.regime]["ratios"]
        qty1, qty2, qty3 = self._split_tp_quantities(live_qty, ratios)
        levels = [(qty1, tp_pxs[0]), (qty2, tp_pxs[1]), (qty3, tp_pxs[2])]

        matched_levels = 0
        expected_prices = []
        for q, px in levels:
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

        if matched_levels < expected:
            return False

        for o in orders:
            if not any(tp_price_matches(o["price"], p, price_tol) for p in expected_prices):
                return False

        if dynamic_sl and not self._has_stop_sl_near(dynamic_sl, price_tol):
            return False
        return True

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
        self, live_qty: float, tolerance: float | None = None, qty_tol: float | None = None
    ) -> int:
        price_tol = self._tp_price_tol() if tolerance is None else float(tolerance)
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        live_qty = self._resolve_live_qty(live_qty)
        ratios = self.regime_settings[self.regime]["ratios"]
        qty1, qty2, qty3 = self._split_tp_quantities(live_qty, ratios)
        levels = [(qty1, self.tv_tps[0]), (qty2, self.tv_tps[1]), (qty3, self.tv_tps[2])]
        placed = 0

        for q, px in levels:
            if q <= 0 or px <= 0:
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
            if self.client.place_limit_order(close_side, q, px, reduce_only=True):
                placed += 1
            time.sleep(0.4)
        return placed

    def _audit_requires_nuclear(self, audit: dict) -> bool:
        expected = audit.get("expected", 0)
        if expected <= 0:
            return False
        if audit.get("matched_full", 0) >= expected and not audit.get("orphans"):
            return False
        if any(lv.get("status") == "duplicate" for lv in audit.get("levels", [])):
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
        rebuilt = False

        for attempt in range(STARTUP_ORDER_FETCH_RETRIES):
            audit = self._audit_tp_levels(live_qty)
            if self._defenses_fully_ok(live_qty, dynamic_sl):
                self._def_log(
                    f"✅ 重启对账：盘口已齐，跳过补挂 | {self._format_audit_summary(audit)}"
                )
                if dynamic_sl and not self._has_stop_sl_near(dynamic_sl):
                    self._ensure_radar_sl(dynamic_sl, live_qty)
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
        placed = self._patch_missing_tp_levels(live_qty)
        if placed:
            rebuilt = True
        time.sleep(0.6)
        if dynamic_sl and not self._has_stop_sl_near(dynamic_sl):
            self._ensure_radar_sl(dynamic_sl, live_qty)

        audit = self._audit_tp_levels(live_qty)
        if self._defenses_fully_ok(live_qty, dynamic_sl):
            self._def_log(
                f"✅ 重启增量纠偏完成 | {self._format_audit_summary(audit)}"
            )
            return self._defense_result_from_audit(audit, skipped=not rebuilt, rebuilt=rebuilt)

        self._def_log(
            f"⚠️ 重启对账后仍不齐，升级智能对齐 | {self._format_audit_summary(audit)}",
            logging.WARNING,
        )
        return self._smart_realign_defenses(
            live_qty, entry, dynamic_sl=dynamic_sl, reason="重启纠偏升级",
        )

    def _cancel_all_tp_limit_orders(self) -> int:
        cancelled = 0
        for o in self.client.get_open_orders(self.symbol) or []:
            if not self._is_tp_limit_order(o):
                continue
            oid = o.get("orderId")
            if oid:
                self.client.cancel_order(self.symbol, int(oid))
                cancelled += 1
                time.sleep(0.15)
        if cancelled:
            self._def_log(f"🧹 已撤销全部限价止盈 {cancelled} 张")
        return cancelled

    def _ensure_radar_sl(self, dynamic_sl, live_qty=None) -> bool:
        if not dynamic_sl:
            return False
        if self._has_stop_sl_near(dynamic_sl):
            return True
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        res = self.client.place_stop_market_order(close_side, dynamic_sl)
        time.sleep(0.35)
        return res is not None

    def _rebuild_tp_limit_orders(self, qty: float, entry: float, dynamic_sl=None) -> int:
        """Legacy _rebuild_defenses: place TP123 by regime ratios; optional SL. Returns placed count."""
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        ratios = self.regime_settings[self.regime]["ratios"]

        live_qty = self._resolve_live_qty(qty)
        if live_qty <= 0:
            self._def_log(f"重建防线跳过：交易所无可用持仓 (传入 {qty} ETH)", logging.WARNING)
            return 0

        if abs(live_qty - qty) > 0.001:
            self.watched_qty = live_qty
            self._save_state()

        qty1, qty2, qty3 = self._split_tp_quantities(live_qty, ratios)
        tp_pxs = self.tv_tps
        placed = 0

        self._def_log(
            f"🕸️ 补挂 TP123: 总 {live_qty} ETH → TP1={qty1} TP2={qty2} TP3={qty3} "
            f"(合计 {round(qty1 + qty2 + qty3, 3)})"
        )

        for q, px in ((qty1, tp_pxs[0]), (qty2, tp_pxs[1]), (qty3, tp_pxs[2])):
            if q > 0 and px > 0:
                res = self.client.place_limit_order(close_side, q, px, reduce_only=True)
                if res:
                    placed += 1
                time.sleep(0.35)

        if dynamic_sl:
            self.client.place_stop_market_order(close_side, dynamic_sl)
        return placed

    def _nuclear_realign_tp(self, live_qty: float, entry: float, dynamic_sl=None, rounds: int = 3) -> dict:
        sl_preserve = dynamic_sl is not None
        last_audit = self._audit_tp_levels(live_qty)
        for r in range(rounds):
            self._def_log(
                f"☢️ 核武级止盈清场重挂 {r + 1}/{rounds} | 持仓 {live_qty} ETH | "
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

        if self._defenses_fully_ok(live_qty, dynamic_sl):
            self._def_log(f"✅ TP123 比例齐全 ({matched}/{expected}) @ {pending_prices}，跳过补挂")
            if dynamic_sl and not self._has_stop_sl_near(dynamic_sl):
                close_side = "SHORT" if self.current_side == "LONG" else "LONG"
                self.client.place_stop_market_order(close_side, dynamic_sl)
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

        if self._defenses_fully_ok(live_qty, dynamic_sl):
            self._def_log(f"✅ 增量补挂成功 ({matched}/{expected}) @ {audit['pending_prices']}")
            if dynamic_sl and not self._has_stop_sl_near(dynamic_sl):
                close_side = "SHORT" if self.current_side == "LONG" else "LONG"
                self.client.place_stop_market_order(close_side, dynamic_sl)
            return matched, audit["pending_prices"], expected, True

        self._def_log(
            f"⚠️ 增量补挂仍不足 ({matched}/{expected}) {audit['issues']}，升级核武级重挂",
            logging.WARNING,
        )
        audit = self._nuclear_realign_tp(live_qty, entry, dynamic_sl=dynamic_sl, rounds=3)
        return audit["matched_full"], audit["pending_prices"], expected, True

    def _smart_realign_defenses(
        self, live_qty: float, entry: float, dynamic_sl=None, reason: str = ""
    ) -> dict:
        """统一智能防线对齐：审计 → 增量或核武 → 仍未达标则强制核武"""
        if reason:
            self._def_log(f"🧠 智能防线对齐: {reason}")
        initial = self._audit_tp_levels(live_qty)
        if self._defenses_fully_ok(live_qty, dynamic_sl):
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
            initial = self._audit_tp_levels(live_qty)
            if self._defenses_fully_ok(live_qty, dynamic_sl):
                return self._defense_result_from_audit(initial, skipped=True)

        if self._audit_requires_nuclear(initial):
            self._def_log("🧹 检测到严重错位，清场后重挂", logging.WARNING)
            self._cancel_all_tp_limit_orders()
            time.sleep(0.5)
            initial = self._audit_tp_levels(live_qty)

        self._cancel_orphan_tp_orders(live_qty)
        matched, pending_prices, expected, rebuilt = self._ensure_defenses_on_recover(
            live_qty, entry, dynamic_sl=dynamic_sl,
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
        """雷达推升：只撤旧止损，TP 增量补挂保留正确单。返回止损是否已成功提交。"""
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        self._cancel_stop_orders()
        time.sleep(0.35)
        sl_placed = False
        if not self._defenses_fully_ok(live_qty, dynamic_sl=None):
            if self._audit_requires_nuclear(self._audit_tp_levels(live_qty)):
                self._nuclear_realign_tp(live_qty, entry, dynamic_sl=new_sl, rounds=2)
                sl_placed = self._has_stop_sl_near(new_sl) or self._ensure_radar_sl(new_sl, live_qty)
            else:
                self._cancel_orphan_tp_orders(live_qty)
                self._patch_missing_tp_levels(live_qty)
                time.sleep(0.6)
                sl_placed = self._ensure_radar_sl(new_sl, live_qty)
        else:
            sl_placed = self.client.place_stop_market_order(close_side, new_sl) is not None
        time.sleep(0.4)
        return sl_placed