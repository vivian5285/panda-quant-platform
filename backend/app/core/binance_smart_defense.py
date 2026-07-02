"""Legacy Binance smart defense stack (_smart_realign_defenses et al.) for multi-user Gemini."""

import logging
import time

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
        return o.get("side") == close_side

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
                "price": round(px, 2),
                "qty": round(float(o.get("origQty", o.get("quantity", 0)) or 0), 3),
            })
        return orders

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

    def _audit_tp_levels(self, live_qty: float, tolerance: float = 1.0, qty_tol: float = 0.005) -> dict:
        live_qty = self._resolve_live_qty(live_qty)
        orders = self._collect_tp_limit_orders()
        levels = []
        matched_full = 0
        issues = []

        for lv in self._expected_tp_levels(live_qty):
            if lv["qty"] <= 0 or lv["price"] <= 0:
                continue
            at_px = [o for o in orders if abs(o["price"] - lv["price"]) <= tolerance]
            status = "ok"
            actual_qty = 0.0
            if len(at_px) == 0:
                status = "missing"
                issues.append(f"TP{lv['level']} @{lv['price']:.2f} 缺失")
            elif len(at_px) > 1:
                status = "duplicate"
                actual_qty = sum(o["qty"] for o in at_px)
                issues.append(f"TP{lv['level']} @{lv['price']:.2f} 重复 {len(at_px)} 张")
            elif abs(at_px[0]["qty"] - lv["qty"]) > qty_tol:
                status = "qty_mismatch"
                actual_qty = at_px[0]["qty"]
                issues.append(
                    f"TP{lv['level']} 数量 {actual_qty} ≠ 期望 {lv['qty']} "
                    f"({self.regime_settings[self.regime]['ratios']})"
                )
            else:
                matched_full += 1
                actual_qty = at_px[0]["qty"]
            levels.append({**lv, "status": status, "actual_qty": actual_qty})

        expected_prices = [lv["price"] for lv in levels]
        orphans = [
            o for o in orders
            if not any(abs(o["price"] - p) <= tolerance for p in expected_prices)
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

    def _count_matched_tp_orders(self, tp_pxs, tolerance: float = 1.0, live_qty=None):
        if live_qty is not None and live_qty > 0:
            audit = self._audit_tp_levels(live_qty, tolerance)
            return audit["matched_full"], audit["pending_prices"]
        pending_prices = self._collect_limit_tp_prices()
        matched = 0
        for tp in tp_pxs:
            if tp <= 0:
                continue
            if any(abs(p - tp) <= tolerance for p in pending_prices):
                matched += 1
        return matched, pending_prices

    def _cancel_orphan_tp_orders(self, live_qty: float, tolerance: float = 1.0) -> int:
        audit = self._audit_tp_levels(live_qty, tolerance)
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

    def _has_duplicate_tp_orders(self, tolerance: float = 1.0) -> bool:
        orders = self._collect_tp_limit_orders()
        expected = self._expected_tp_count()
        if expected <= 0:
            return False
        if len(orders) > expected:
            return True
        for tp in self.tv_tps:
            if tp <= 0:
                continue
            at_px = [o for o in orders if abs(o["price"] - tp) <= tolerance]
            if len(at_px) > 1:
                return True
        return False

    def _defenses_fully_ok(
        self, live_qty: float, dynamic_sl=None, tolerance: float = 1.0, qty_tol: float = 0.005
    ) -> bool:
        tp_pxs = self.tv_tps
        expected = self._expected_tp_count(tp_pxs)
        if expected == 0:
            return dynamic_sl is None or self._has_stop_sl_near(dynamic_sl, tolerance)

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
            at_px = [o for o in orders if abs(o["price"] - px) <= tolerance]
            if len(at_px) != 1:
                return False
            if abs(at_px[0]["qty"] - q) > qty_tol:
                return False
            matched_levels += 1

        if matched_levels < expected:
            return False

        for o in orders:
            if not any(abs(o["price"] - p) <= tolerance for p in expected_prices):
                return False

        if dynamic_sl and not self._has_stop_sl_near(dynamic_sl, tolerance):
            return False
        return True

    def _patch_missing_tp_levels(self, live_qty: float, tolerance: float = 1.0, qty_tol: float = 0.005) -> int:
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
            at_px = [o for o in orders if abs(o["price"] - px) <= tolerance]
            if len(at_px) == 1 and abs(at_px[0]["qty"] - q) <= qty_tol:
                self._def_log(f"  ✓ TP @ {px:.2f} 已存在 {at_px[0]['qty']} ETH，跳过")
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
        orders = self._collect_tp_limit_orders()
        if len(orders) > expected:
            return True
        if audit.get("matched_full", 0) == 0 and audit.get("issues"):
            return True
        bad = [
            lv for lv in audit.get("levels", [])
            if lv.get("status") in ("duplicate", "qty_mismatch")
        ]
        if bad:
            return True
        missing = sum(1 for lv in audit.get("levels", []) if lv.get("status") == "missing")
        if missing >= 2:
            return True
        if audit.get("orphans"):
            return True
        return False

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

        if self._audit_requires_nuclear(audit) or self._has_duplicate_tp_orders():
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