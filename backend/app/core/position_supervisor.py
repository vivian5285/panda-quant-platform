import json
import logging
import os
import threading
import time
from typing import Callable, Optional

from app.core.binance_client import BinanceClient
from app.core.position_manager import PositionManager
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

        self.regime_settings = {
            1: {"margin": 0.15, "ratios": [0.25, 0.35, 0.40], "trail": 0.55},
            2: {"margin": 0.25, "ratios": [0.20, 0.35, 0.45], "trail": 0.60},
            3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "trail": 0.65},
            4: {"margin": 0.50, "ratios": [0.05, 0.20, 0.75], "trail": 0.70},
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
                    self.tv_tps = s.get("tv_tps", [0.0, 0.0, 0.0])
        except Exception as e:
            logger.error(f"[User {self.user_id}] load state failed: {e}")

    def handle_signal(self, payload: dict):
        raw_action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        if self.regime not in self.regime_settings:
            self.regime = 3

        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_price = float(payload.get("price", 0.0))
        self.tv_tps = [
            float(payload.get("tv_tp1", 0)),
            float(payload.get("tv_tp2", 0)),
            float(payload.get("tv_tp3", 0)),
        ]
        close_reason = payload.get("reason", "策略指标反转/波动率安全退出")

        if not raw_action:
            return
        if not self._lock.acquire(timeout=10.0):
            self._alert("warning", "LOCK_TIMEOUT", "信号处理超时", f"用户 {self.user_id} 锁等待超时，信号被丢弃")
            return

        try:
            self.monitoring = False
            if raw_action == "CLOSE_PROTECT" or raw_action.startswith("CLOSE_PROTECT") or "CLOSE_PROTECT" in raw_action:
                self._close_all(f"保护性全平：{close_reason}")
            elif raw_action == "CLOSE_TP3":
                self._close_all("TP3 终极收网")
            elif raw_action == "CLOSE":
                self._close_all(f"换防清场：{close_reason}")
            elif raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self._save_state()
                self._handle_smart_entry(raw_action)
        finally:
            self._lock.release()

    def _handle_smart_entry(self, action: str):
        self._log("SIGNAL", f"收到建仓信号 [{action}]，启动先平后开")
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)

        pos = self.position_manager.get_position(self.symbol)
        if pos and float(pos.get("positionAmt", 0)) != 0:
            current_side = "LONG" if float(pos["positionAmt"]) > 0 else "SHORT"
            if current_side == action:
                self._close_all("同方向新指令，先平后开洗清旧阵地")
            else:
                self._close_all("反方向指令，先平后开原子换防")
            time.sleep(1.2)

        curr_px = self.client.get_current_price(self.symbol)
        if curr_px > 0:
            self._open_position(action, curr_px)

    def _open_position(self, action: str, curr_px: float):
        self.client.ensure_one_way_mode()
        balance = self.client.get_available_balance()
        margin_pct = self.regime_settings[self.regime]["margin"]
        self.client.set_leverage(self.symbol, leverage=self.leverage)
        qty = round((balance * margin_pct * self.leverage) / curr_px, 3)
        if qty <= 0:
            self._log("ERROR", "余额不足，无法开仓")
            self._alert("warning", "INSUFFICIENT_BALANCE", "余额不足", f"用户 {self.user_id} 无法开仓")
            return

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
            slip = (entry_price - self.tv_price) if action == "LONG" else (self.tv_price - entry_price)
            detail = {
                "regime": self.regime,
                "qty": real_qty,
                "entry": entry_price,
                "tv_price": self.tv_price,
                "slippage": round(slip, 2),
                "tv_tps": self.tv_tps,
                "margin_pct": margin_pct,
                "leverage": self.leverage,
            }
            self._log("OPEN", f"唯一主仓 {action} {real_qty} @ {entry_price}", detail)
            self._alert(
                "info", "OPEN",
                f"开仓 {action} · Regime {self.regime}",
                f"{real_qty} ETH @ {entry_price} | 滑点 {slip:+.2f} | TP {self.tv_tps}",
                detail,
            )
            self._protect_and_monitor(real_qty, entry_price)

    def _protect_and_monitor(self, qty: float, entry_price: float):
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        ratios = self.regime_settings[self.regime]["ratios"]
        qty1 = round(qty * ratios[0], 3)
        qty2 = round(qty * ratios[1], 3)
        qty3 = round(qty - qty1 - qty2, 3)
        tp_pxs = self.tv_tps
        self.current_sl = entry_price
        self.best_price = entry_price

        if qty1 > 0 and tp_pxs[0] > 0:
            self.client.place_limit_order(close_side, qty1, tp_pxs[0], self.symbol)
        if qty2 > 0 and tp_pxs[1] > 0:
            self.client.place_limit_order(close_side, qty2, tp_pxs[1], self.symbol)
        if qty3 > 0 and tp_pxs[2] > 0:
            self.client.place_limit_order(close_side, qty3, tp_pxs[2], self.symbol)

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
                    if real_amt == 0:
                        if self.watched_qty > 0:
                            self._close_all("仓位归零（止盈吃单或 TV 强制平仓）")
                        break

                    actual_side = "LONG" if real_amt > 0 else "SHORT"
                    if actual_side != self.last_tv_side:
                        self._alert(
                            "critical", "FORCE_ALIGN",
                            "方向背离 · 强制全平",
                            f"实盘 {actual_side} vs TV {self.last_tv_side}，禁止逆势持仓",
                            {"actual_side": actual_side, "tv_side": self.last_tv_side},
                        )
                        self._close_all(f"方向背离：实盘({actual_side}) vs TV({self.last_tv_side})")
                        break

                    actual_qty = abs(real_amt)
                    if abs(actual_qty - self.watched_qty) > 0.001:
                        old_qty = self.watched_qty
                        self.watched_qty = actual_qty
                        self.watched_entry = float(pos["entryPrice"])
                        self.client.cancel_all_open_orders(self.symbol)
                        time.sleep(0.5)
                        sl_to_pass = None
                        if (self.current_side == "LONG" and self.current_sl > self.watched_entry) or (
                            self.current_side == "SHORT" and self.current_sl < self.watched_entry
                        ):
                            sl_to_pass = self.current_sl
                        self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=sl_to_pass)
                        self._save_state()
                        action_msg = "手动加仓" if actual_qty > old_qty else "部分止盈/手动减仓"
                        detail = {"old_qty": old_qty, "new_qty": actual_qty, "entry": self.watched_entry}
                        self._log("ADJUST", f"仓位变化 {old_qty}→{actual_qty}，重构防线", detail)
                        self._alert(
                            "warning", "MANUAL_ADJUST",
                            f"阵地异动 · {action_msg}",
                            f"数量 {old_qty} → {actual_qty} @ {self.watched_entry}",
                            detail,
                        )

                    curr_px = self.client.get_current_price(self.symbol)
                    if self.current_side == "LONG":
                        self.best_price = max(self.best_price, curr_px)
                    else:
                        self.best_price = min(self.best_price, curr_px) if self.best_price else curr_px

                    tp1_dist = abs(self.tv_tps[0] - self.watched_entry) if self.tv_tps[0] > 0 else self.current_atr * 1.5
                    trail_factor = self.regime_settings[self.regime]["trail"]
                    activation_ratio = 0.45 if self.regime >= 3 else 0.60
                    required = (
                        self.watched_entry + tp1_dist * activation_ratio
                        if self.current_side == "LONG"
                        else self.watched_entry - tp1_dist * activation_ratio
                    )
                    has_moved = curr_px >= required if self.current_side == "LONG" else curr_px <= required

                    if has_moved:
                        trail_offset = self.current_atr * trail_factor * 0.45
                        if self.current_side == "LONG":
                            new_sl = max(round(self.best_price - trail_offset, 2), self.watched_entry + 1.0)
                            if new_sl > self.current_sl + 2.0:
                                self.client.cancel_all_open_orders(self.symbol)
                                time.sleep(0.5)
                                self.current_sl = new_sl
                                self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=new_sl)
                                self._save_state()
                                self._log("TRAIL", f"雷达锁润 SL → {new_sl}")
                                self._alert(
                                    "info", "TRAIL",
                                    "雷达激活 · 锁润推升",
                                    f"SL {new_sl} | 仓位 {actual_qty} @ {self.watched_entry}",
                                    {"new_sl": new_sl, "best_price": self.best_price},
                                )
                        else:
                            new_sl = min(round(self.best_price + trail_offset, 2), self.watched_entry - 1.0)
                            if self.current_sl >= self.watched_entry or new_sl < self.current_sl - 2.0:
                                self.client.cancel_all_open_orders(self.symbol)
                                time.sleep(0.5)
                                self.current_sl = new_sl
                                self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=new_sl)
                                self._save_state()
                                self._log("TRAIL", f"雷达锁润 SL → {new_sl}")
                                self._alert(
                                    "info", "TRAIL",
                                    "雷达激活 · 锁润下压",
                                    f"SL {new_sl} | 仓位 {actual_qty} @ {self.watched_entry}",
                                    {"new_sl": new_sl, "best_price": self.best_price},
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
        qty1 = round(qty * ratios[0], 3)
        qty2 = round(qty * ratios[1], 3)
        qty3 = round(qty - qty1 - qty2, 3)
        tp_pxs = self.tv_tps

        if qty1 > 0 and tp_pxs[0] > 0:
            self.client.place_limit_order(close_side, qty1, tp_pxs[0], self.symbol)
        if qty2 > 0 and tp_pxs[1] > 0:
            self.client.place_limit_order(close_side, qty2, tp_pxs[1], self.symbol)
        if qty3 > 0 and tp_pxs[2] > 0:
            self.client.place_limit_order(close_side, qty3, tp_pxs[2], self.symbol)
        if dynamic_sl:
            self.client.place_stop_market_order(close_side, dynamic_sl, self.symbol)

    def _close_all(self, reason: str = ""):
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        closed = False
        exit_price = self.client.get_current_price(self.symbol)

        for _ in range(5):
            pos = self.position_manager.get_position(self.symbol)
            if not pos or float(pos.get("positionAmt", 0)) == 0:
                closed = True
                break
            close_side = "SELL" if float(pos["positionAmt"]) > 0 else "BUY"
            self.client.place_market_order(
                close_side, abs(float(pos["positionAmt"])), self.symbol, reduce_only=True
            )
            time.sleep(1.5)

        if closed and self.current_trade_id:
            pnl = 0.0
            if self.watched_entry and exit_price:
                diff = exit_price - self.watched_entry
                if self.current_side == "SHORT":
                    diff = -diff
                pnl = diff * self.watched_qty
            self.on_trade_close(self.current_trade_id, exit_price, pnl, reason)
            self._log("CLOSE", reason, {"exit_price": exit_price, "pnl": pnl})
            sev = "critical" if "背离" in reason else "info"
            self._alert(sev, "CLOSE", "全平完成", reason, {"exit_price": exit_price, "pnl": pnl})

        self.monitoring = False
        self.watched_qty = 0.0
        self.current_trade_id = None
        self._save_state()
        self.client.cancel_all_open_orders(self.symbol)

    def recover_on_startup(self, open_trade_id: int | None = None) -> dict:
        """VPS 自启强制账户接管：恢复状态、重建防线、启动哨兵。"""
        self.client.ensure_one_way_mode()
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
            self.watched_entry = float(pos["entryPrice"])
            if self.best_price <= 0:
                self.best_price = self.watched_entry
            if self.current_sl <= 0:
                self.current_sl = self.watched_entry
            self.current_trade_id = open_trade_id

            audit.update({
                "has_position": True,
                "side": self.current_side,
                "qty": self.watched_qty,
                "entry": self.watched_entry,
                "last_tv_side": self.last_tv_side,
                "direction_aligned": self.current_side == self.last_tv_side,
                "tv_tps": list(self.tv_tps),
                "current_sl": self.current_sl,
            })

            if not audit["direction_aligned"]:
                self._alert(
                    "critical", "STARTUP_MISMATCH",
                    "自启方向背离",
                    f"实盘 {self.current_side} vs TV {self.last_tv_side}，哨兵将强制对齐",
                    audit,
                )
                self._log("STARTUP", f"方向背离 实盘({self.current_side}) vs TV({self.last_tv_side})", audit)
            else:
                self.client.cancel_all_open_orders(self.symbol)
                time.sleep(0.5)
                self._rebuild_defenses(self.watched_qty, self.watched_entry)
                audit["defenses_rebuilt"] = True

            self.monitoring = True
            audit["monitoring"] = True
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
