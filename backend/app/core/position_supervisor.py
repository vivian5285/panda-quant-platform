import json
import logging
import os
import threading
import time
from typing import Callable, Optional

from app.core.binance_client import BinanceClient
from app.core.position_manager import PositionManager
from app.core.symbol_precision import normalize_tv_targets, round_price, round_quantity
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class PositionSupervisor:
    """
    多用户版 position_supervisor_binance.py
    TV 军师指挥价格/regime → VPS 自主执行仓位管理、止盈网格、雷达锁润、先平后开、单向持仓。
    """

    def __init__(
        self,
        user_id: int,
        client: BinanceClient,
        on_log: Optional[Callable] = None,
        on_trade_open: Optional[Callable] = None,
        on_trade_close: Optional[Callable] = None,
        on_alert: Optional[Callable] = None,
    ):
        self.user_id = user_id
        self.client = client
        self.position_manager = PositionManager(client)
        self.on_log = on_log or (lambda *a, **k: None)
        self.on_trade_open = on_trade_open or (lambda *a, **k: None)
        self.on_trade_close = on_trade_close or (lambda *a, **k: None)
        self.on_alert = on_alert or (lambda *a, **k: None)
        self._sentinel_error_notified = False

        self.symbol = settings.SYMBOL
        self.leverage = settings.LEVERAGE
        self.monitoring = False
        self._lock = threading.Lock()
        self.trade_opened_at: float | None = None

        # activation: 到达 TP1 距离的比例后启动保本盾；trail_offset: 锁润止损距极值的 ATR 倍数
        self.regime_settings = {
            1: {"margin": 0.15, "ratios": [0.25, 0.35, 0.40], "activation": 0.40, "trail_offset": 0.40},
            2: {"margin": 0.25, "ratios": [0.20, 0.35, 0.45], "activation": 0.50, "trail_offset": 0.60},
            3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
            4: {"margin": 0.50, "ratios": [0.05, 0.20, 0.75], "activation": 0.70, "trail_offset": 1.30},
        }

        self.regime = 3
        self.current_atr = 30.0
        self.best_price = 0.0
        self.current_sl = 0.0
        self.tv_price = 0.0
        self.initial_qty = 0.0
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_side = None
        self.last_tv_side = None
        self.tv_tps = [0.0, 0.0, 0.0]
        self.current_trade_id = None
        self.risk_multiplier = 1.0

        os.makedirs("state", exist_ok=True)
        self.state_file = f"state/user_{user_id}.json"
        self._load_state()

    def _log(self, event_type: str, message: str, detail: dict | None = None):
        self.on_log(self.user_id, event_type, message, detail, self.current_trade_id)

    def _alert(self, severity: str, alert_type: str, title: str, message: str, detail: dict | None = None):
        self.on_alert(self.user_id, severity, alert_type, title, message, detail)

    def _save_state(self):
        try:
            with open(self.state_file, "w") as f:
                json.dump({
                    "last_tv_side": self.last_tv_side,
                    "current_side": self.current_side,
                    "watched_qty": self.watched_qty,
                    "watched_entry": self.watched_entry,
                    "current_sl": self.current_sl,
                    "best_price": self.best_price,
                    "regime": self.regime,
                    "current_atr": self.current_atr,
                    "monitoring": self.monitoring,
                    "tv_tps": self.tv_tps,
                }, f)
        except Exception as e:
            logger.error(f"[User {self.user_id}] save state failed: {e}")

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file) as f:
                    s = json.load(f)
                    self.last_tv_side = s.get("last_tv_side")
                    self.current_side = s.get("current_side")
                    self.watched_qty = float(s.get("watched_qty", 0) or 0)
                    self.watched_entry = float(s.get("watched_entry", 0) or 0)
                    self.current_sl = float(s.get("current_sl", 0) or 0)
                    self.best_price = float(s.get("best_price", 0) or 0)
                    self.regime = int(s.get("regime", 3) or 3)
                    self.current_atr = float(s.get("current_atr", 30) or 30)
                    self.monitoring = bool(s.get("monitoring", False))
                    self.tv_tps = normalize_tv_targets(s.get("tv_tps", [0.0, 0.0, 0.0]))
        except Exception as e:
            logger.error(f"[User {self.user_id}] load state failed: {e}")

    def handle_signal(self, payload: dict) -> dict:
        raw_action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        if self.regime not in self.regime_settings:
            self.regime = 3

        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_price = round_price(payload.get("price", 0))
        self.tv_tps = normalize_tv_targets([
            payload.get("tv_tp1", 0),
            payload.get("tv_tp2", 0),
            payload.get("tv_tp3", 0),
        ])
        self.risk_multiplier = float(payload.get("risk_multiplier", 1.0))
        close_reason = payload.get("reason", "策略指标反转/波动率安全退出")

        if not raw_action:
            return {"status": "skipped", "reason": "empty_action"}
        if not self._lock.acquire(timeout=10.0):
            self._alert("warning", "LOCK_TIMEOUT", "信号处理超时", f"用户 {self.user_id} 锁等待超时，信号被丢弃")
            return {"status": "skipped", "reason": "lock_timeout"}

        try:
            self.monitoring = False
            if raw_action == "CLOSE_PROTECT" or raw_action.startswith("CLOSE_PROTECT"):
                self._close_all(f"🛡️ 保护性全平：{close_reason}")
                return {"status": "ok", "action": raw_action, "detail": {"type": "close_protect"}}
            if raw_action == "CLOSE_TP3":
                self._close_all("🎯 完美胜利：大趋势吃满，TP3 终极收网")
                return {"status": "ok", "action": raw_action, "detail": {"type": "close_tp3"}}
            if raw_action == "CLOSE":
                self._close_all(f"🧹 换防清场：{close_reason}")
                return {"status": "ok", "action": raw_action, "detail": {"type": "close"}}
            if raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self._save_state()
                return self._handle_smart_entry(raw_action)
            return {"status": "skipped", "reason": "unknown_action", "detail": {"action": raw_action}}
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            self._lock.release()

    def _handle_smart_entry(self, action: str) -> dict:
        self._log("SIGNAL", f"⚡ 收到建仓信号 [{action}]，启动绝对先平后开机制")
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)

        pos = self.position_manager.get_position(self.symbol)
        if pos and float(pos.get("positionAmt", 0)) != 0:
            current_side = "LONG" if float(pos["positionAmt"]) > 0 else "SHORT"
            if current_side == action:
                self._close_all("同方向新指令到达，触发【先平后开】洗清旧阵地")
            else:
                self._close_all("反方向指令到达，触发【先平后开】原子对冲换防")
            time.sleep(1.2)

        curr_px = self.client.get_current_price(self.symbol)
        if curr_px > 0:
            return self._open_position(action, curr_px)
        return {"status": "error", "reason": "price_unavailable", "message": "无法获取当前价格"}

    def _open_position(self, action: str, curr_px: float) -> dict:
        balance = self.client.get_available_balance()
        margin_pct = self.regime_settings[self.regime]["margin"] * self.risk_multiplier
        self.client.set_leverage(self.symbol, leverage=self.leverage)
        qty = round_quantity((balance * margin_pct * self.leverage) / curr_px)
        if qty <= 0:
            self._log("ERROR", "余额不足，无法开仓")
            self._alert("warning", "INSUFFICIENT_BALANCE", "余额不足", f"用户 {self.user_id} 无法开仓")
            return {"status": "error", "reason": "insufficient_balance", "message": "余额不足，无法开仓"}

        open_side = "BUY" if action == "LONG" else "SELL"
        self._log("SIGNAL", f"🚀 [唯一主仓] 极速开仓: {open_side} {qty} 个ETH | 档位 {self.regime}")
        self.client.place_market_order(action, qty, self.symbol)
        time.sleep(2.0)

        pos = self.position_manager.get_position(self.symbol)
        if pos and float(pos.get("positionAmt", 0)) != 0:
            self.current_side = action
            real_qty = abs(float(pos["positionAmt"]))
            entry_price = float(pos["entryPrice"])
            self.initial_qty = real_qty
            self.current_trade_id = self.on_trade_open(
                self.user_id, action, real_qty, entry_price, self.regime, self.tv_tps
            )
            self.trade_opened_at = time.time()
            slip = (entry_price - self.tv_price) if action == "LONG" else (self.tv_price - entry_price)
            detail = {
                "regime": self.regime,
                "side": action,
                "qty": real_qty,
                "entry": entry_price,
                "tv_price": self.tv_price,
                "slippage": round(slip, 2),
                "tv_tps": list(self.tv_tps),
                "margin_pct": margin_pct,
                "risk_multiplier": self.risk_multiplier,
                "leverage": self.leverage,
                "atr": self.current_atr,
            }
            self._log("OPEN", f"🔶 战神出击：{action} {real_qty} ETH @ {entry_price} | 滑点 {slip:+.2f}", detail)
            self._alert(
                "info", "OPEN",
                "🔶 战神出击：币安大级别阵地建立",
                f"{action} {real_qty} ETH @ {entry_price} | 滑点 {slip:+.2f} | TP {self.tv_tps} | ATR {self.current_atr}",
                detail,
            )
            self._protect_and_monitor(real_qty, entry_price)
            return {
                "status": "ok",
                "action": action,
                "slippage": round(slip, 4),
                "trade_id": self.current_trade_id,
                "detail": detail,
            }
        return {"status": "error", "reason": "open_failed", "message": "下单后未检测到持仓"}

    def _protect_and_monitor(self, qty: float, entry_price: float):
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        ratios = self.regime_settings[self.regime]["ratios"]
        qty1 = round_quantity(qty * ratios[0])
        qty2 = round_quantity(qty * ratios[1])
        qty3 = round_quantity(qty - qty1 - qty2)
        tp_pxs = self.tv_tps
        self.current_sl = entry_price

        if qty1 > 0 and tp_pxs[0] > 0:
            self.client.place_limit_order(close_side, qty1, tp_pxs[0], self.symbol, reduce_only=True)
        if qty2 > 0 and tp_pxs[1] > 0:
            self.client.place_limit_order(close_side, qty2, tp_pxs[1], self.symbol, reduce_only=True)
        if qty3 > 0 and tp_pxs[2] > 0:
            self.client.place_limit_order(close_side, qty3, tp_pxs[2], self.symbol, reduce_only=True)

        self.best_price = entry_price
        self.watched_qty = qty
        self.watched_entry = entry_price
        self.monitoring = True
        self._save_state()
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                if not self._lock.acquire(timeout=2.0):
                    continue
                try:
                    pos = self.position_manager.get_position(self.symbol)
                    real_amt = float(pos.get("positionAmt", 0)) if pos else 0.0
                    actual_side = "LONG" if real_amt > 0 else "SHORT"
                    actual_qty = abs(real_amt)

                    if real_amt == 0:
                        if self.watched_qty > 0:
                            self._close_all("仓位归零 (达到目标止盈或 TV 强制平仓)")
                        break

                    if actual_side != self.last_tv_side:
                        self._alert(
                            "critical", "FORCE_ALIGN",
                            "方向背离 · 强制全平",
                            f"实盘 {actual_side} vs TV {self.last_tv_side}，禁止逆势持仓",
                            {"actual_side": actual_side, "tv_side": self.last_tv_side},
                        )
                        self._close_all(f"致命方向背离：实盘({actual_side}) vs TV({self.last_tv_side})")
                        break

                    if abs(actual_qty - self.watched_qty) > 0.001:
                        old_qty = self.watched_qty
                        self.watched_qty = actual_qty
                        self.watched_entry = float(pos["entryPrice"])
                        self.client.cancel_all_open_orders(self.symbol)
                        time.sleep(0.5)
                        sl_to_pass = (
                            self.current_sl
                            if (self.current_side == "LONG" and self.current_sl > self.watched_entry)
                            or (self.current_side == "SHORT" and self.current_sl < self.watched_entry)
                            else None
                        )
                        self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=sl_to_pass)
                        action_msg = "手动加仓" if actual_qty > old_qty else "部分止盈吃单 / 手动减仓"
                        detail = {
                            "old_qty": old_qty,
                            "new_qty": actual_qty,
                            "entry": self.watched_entry,
                            "action_msg": action_msg,
                        }
                        self._log("ADJUST", f"🔄 感知到仓位变化: {old_qty} ➔ {actual_qty}，重新重构防线", detail)
                        self._alert(
                            "warning", "MANUAL_ADJUST",
                            f"阵地异动 · {action_msg}",
                            f"数量 {old_qty} → {actual_qty} @ {self.watched_entry}",
                            detail,
                        )

                    curr_px = self.client.get_current_price(self.symbol)
                    self.best_price = (
                        max(self.best_price, curr_px)
                        if self.current_side == "LONG"
                        else min(self.best_price, curr_px)
                    )

                    tp1_dist = (
                        abs(self.tv_tps[0] - self.watched_entry)
                        if self.tv_tps[0] > 0
                        else self.current_atr * 1.5
                    )
                    cfg = self.regime_settings[self.regime]
                    activation_ratio = cfg["activation"]
                    trail_atr_multiplier = cfg["trail_offset"]
                    required = (
                        self.watched_entry + (tp1_dist * activation_ratio)
                        if self.current_side == "LONG"
                        else self.watched_entry - (tp1_dist * activation_ratio)
                    )
                    has_moved_favorably = (
                        curr_px >= required if self.current_side == "LONG" else curr_px <= required
                    )

                    if has_moved_favorably:
                        trail_offset = self.current_atr * trail_atr_multiplier
                        fee_buffer = self.watched_entry * 0.0015

                        if self.current_side == "LONG":
                            breakeven_floor = round_price(self.watched_entry + fee_buffer)
                            new_sl = round_price(max(self.best_price - trail_offset, breakeven_floor))
                            if new_sl > self.current_sl + 1.0:
                                self.client.cancel_all_open_orders(self.symbol)
                                time.sleep(0.5)
                                self.current_sl = new_sl
                                self._save_state()
                                self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=new_sl)
                                trail_msg = f"🚀 档位{self.regime} 雷达激活：保本盾升起，锁润底线物理推升！"
                                trail_detail = {
                                    "regime": self.regime,
                                    "new_sl": new_sl,
                                    "best_price": self.best_price,
                                    "entry": self.watched_entry,
                                    "qty": actual_qty,
                                    "activation_ratio": activation_ratio,
                                    "trail_offset_atr": trail_atr_multiplier,
                                    "fee_buffer": round(fee_buffer, 4),
                                }
                                self._log("TRAIL", trail_msg, trail_detail)
                                self._alert(
                                    "info", "TRAIL",
                                    "📈 捷报：追踪雷达锁死趋势利润",
                                    f"SL {new_sl} | 仓位 {actual_qty} @ {self.watched_entry}",
                                    trail_detail,
                                )
                        else:
                            breakeven_floor = round_price(self.watched_entry - fee_buffer)
                            new_sl = round_price(min(self.best_price + trail_offset, breakeven_floor))
                            if self.current_sl >= self.watched_entry or new_sl < self.current_sl - 1.0:
                                self.client.cancel_all_open_orders(self.symbol)
                                time.sleep(0.5)
                                self.current_sl = new_sl
                                self._save_state()
                                self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=new_sl)
                                trail_msg = f"🚀 档位{self.regime} 雷达激活：保本盾降下，锁润顶线物理下压！"
                                trail_detail = {
                                    "regime": self.regime,
                                    "new_sl": new_sl,
                                    "best_price": self.best_price,
                                    "entry": self.watched_entry,
                                    "qty": actual_qty,
                                    "activation_ratio": activation_ratio,
                                    "trail_offset_atr": trail_atr_multiplier,
                                    "fee_buffer": round(fee_buffer, 4),
                                }
                                self._log("TRAIL", trail_msg, trail_detail)
                                self._alert(
                                    "info", "TRAIL",
                                    "📈 捷报：追踪雷达锁死趋势利润",
                                    f"SL {new_sl} | 仓位 {actual_qty} @ {self.watched_entry}",
                                    trail_detail,
                                )
                    self._sentinel_error_notified = False
                finally:
                    self._lock.release()
            except Exception as e:
                logger.error(f"[User {self.user_id}] sentinel error: {e}")
                if not self._sentinel_error_notified:
                    self._alert(
                        "critical", "SENTINEL_ERROR",
                        "哨兵监控异常",
                        str(e),
                        {"user_id": self.user_id},
                    )
                    self._sentinel_error_notified = True
            time.sleep(6)

    def _rebuild_defenses(self, qty: float, entry: float, dynamic_sl=None):
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        ratios = self.regime_settings[self.regime]["ratios"]
        qty1 = round_quantity(qty * ratios[0])
        qty2 = round_quantity(qty * ratios[1])
        qty3 = round_quantity(qty - qty1 - qty2)
        tp_pxs = self.tv_tps

        if qty1 > 0 and tp_pxs[0] > 0:
            self.client.place_limit_order(close_side, qty1, tp_pxs[0], self.symbol, reduce_only=True)
        if qty2 > 0 and tp_pxs[1] > 0:
            self.client.place_limit_order(close_side, qty2, tp_pxs[1], self.symbol, reduce_only=True)
        if qty3 > 0 and tp_pxs[2] > 0:
            self.client.place_limit_order(close_side, qty3, tp_pxs[2], self.symbol, reduce_only=True)
        if dynamic_sl:
            self.client.place_stop_market_order(close_side, round_price(dynamic_sl), self.symbol)

    def _close_all(self, reason: str = ""):
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        closed_successfully = False
        exit_price = self.client.get_current_price(self.symbol)

        for _ in range(5):
            pos = self.position_manager.get_position(self.symbol)
            if not pos or float(pos.get("positionAmt", 0)) == 0:
                closed_successfully = True
                break
            close_side = "SELL" if float(pos["positionAmt"]) > 0 else "BUY"
            self.client.place_market_order(
                close_side, abs(float(pos["positionAmt"])), self.symbol
            )
            time.sleep(1.5)

        if reason and closed_successfully and self.current_trade_id:
            pnl = 0.0
            if self.watched_entry and exit_price:
                diff = exit_price - self.watched_entry
                if self.current_side == "SHORT":
                    diff = -diff
                pnl = diff * self.watched_qty
            start_ms = int(self.trade_opened_at * 1000) if self.trade_opened_at else None
            funding_fee = self.client.get_funding_fees(self.symbol, start_ms)
            close_detail = {
                "exit_price": exit_price,
                "pnl": round(pnl, 4),
                "funding_fee": funding_fee,
                "reason": reason,
                "regime": self.regime,
                "side": self.current_side,
                "qty": self.watched_qty,
                "entry": self.watched_entry,
            }
            self.on_trade_close(self.current_trade_id, exit_price, pnl, reason, funding_fee)
            self._log("CLOSE", reason, close_detail)
            sev = "critical" if "背离" in reason else "info"
            self._alert(sev, "CLOSE", "全平完成", reason, close_detail)

        self.monitoring = False
        self.watched_qty = 0.0
        self.current_trade_id = None
        self.trade_opened_at = None
        self._save_state()
        self.client.cancel_all_open_orders(self.symbol)

    def recover_on_startup(self, open_trade_id: int | None = None) -> dict:
        """VPS 自启账户接管（与单账户 recover_state_on_startup 一致）。"""
        audit = {
            "user_id": self.user_id,
            "has_position": False,
            "side": None,
            "qty": 0.0,
            "entry": 0.0,
            "last_tv_side": self.last_tv_side,
            "direction_aligned": True,
            "tv_tps": list(self.tv_tps),
            "current_sl": self.current_sl,
            "monitoring": False,
            "defenses_rebuilt": False,
            "open_trade_id": open_trade_id,
        }
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file) as f:
                    s = json.load(f)
                    self.last_tv_side = s.get("last_tv_side", self.last_tv_side)
                    self.tv_tps = s.get("tv_tps", self.tv_tps)

            pos = self.position_manager.get_position(self.symbol)
            if not pos or float(pos.get("positionAmt", 0)) == 0:
                self.monitoring = False
                self._log("STARTUP", "VPS 自启审计：空仓待机")
                return audit

            real_amt = float(pos["positionAmt"])
            self.current_side = "LONG" if real_amt > 0 else "SHORT"
            if not self.last_tv_side:
                self.last_tv_side = self.current_side

            self.watched_qty = abs(real_amt)
            self.initial_qty = abs(real_amt)
            self.watched_entry = float(pos["entryPrice"])
            self.best_price = self.watched_entry
            self.current_sl = self.watched_entry
            self.current_trade_id = open_trade_id
            self.monitoring = True

            audit.update({
                "has_position": True,
                "side": self.current_side,
                "qty": self.watched_qty,
                "entry": self.watched_entry,
                "last_tv_side": self.last_tv_side,
                "direction_aligned": self.current_side == self.last_tv_side,
                "tv_tps": list(self.tv_tps),
                "current_sl": self.current_sl,
                "monitoring": True,
            })
            self._save_state()
            threading.Thread(target=self._sentinel_loop, daemon=True).start()

            self._log("STARTUP", f"账户接管 {self.current_side} {self.watched_qty} @ {self.watched_entry}", audit)
            self._alert(
                "info", "STARTUP",
                "VPS 账户接管完成",
                f"{self.current_side} {self.watched_qty} @ {self.watched_entry}",
                audit,
            )
        except Exception as e:
            logger.error(f"[User {self.user_id}] recover failed: {e}")
            audit["error"] = str(e)
            self._alert(
                "critical", "STARTUP_FAIL",
                "自启接管失败",
                str(e),
                audit,
            )
        return audit
