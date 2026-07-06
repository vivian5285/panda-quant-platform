import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.core.binance_client import BinanceClient
from app.core.adverse_radar_guard import ADVERSE_ARM_PCT, AdverseRadarMixin
from app.core.binance_smart_defense import BinanceSmartDefenseMixin
from app.core.position_cap_guard import PositionCapGuardMixin
from app.core.position_manager import PositionManager
from app.core.regime_utils import clamp_regime
from app.core.same_direction_policy import (
    SameDirAction,
    evaluate_same_direction,
    format_refresh_reason,
    format_reopen_reason,
)
from app.core.close_attribution import diagnose_flat_close, format_close_reason
from app.core.symbol_precision import normalize_tv_targets, round_price, round_quantity, PRICE_TICK
from app.core.position_sizing import compute_eth_qty
from app.config import get_settings
from app.services.trading_alerts import resolve_exchange_theme

logger = logging.getLogger(__name__)
settings = get_settings()
MIN_SL_MOVE = float(PRICE_TICK)  # ETHUSDT tick 0.01 — minimum SL trail step
TP_RETRY_MAX = 3
TP_RETRY_DELAY = 0.8  # seconds; multiplied by attempt index
CANCEL_VERIFY_ROUNDS = 5
HEAL_PLACE_ROUNDS = 2
SIGNAL_QUEUE_TTL = 120.0
SIGNAL_LOCK_SLICE = 5.0
SENTINEL_POLL_NORMAL = 6
SENTINEL_POLL_ARMING = 3
SENTINEL_POLL_RADAR = 2
DUST_QTY_ETH = 0.004
TP_COMPLETE_RESIDUAL_RATIO = 0.12
RADAR_SL_MIN_MOVE = 1.0
FLAT_WAIT_TIMEOUT = 12.0
FLAT_WAIT_POLL = 0.6
FLAT_CONFIRM_POLLS = 3
FLAT_CONFIRM_DELAY = 0.45


@dataclass
class _QueuedSignal:
    payload: dict
    enqueued_at: float
    event: threading.Event = field(default_factory=threading.Event)
    result: dict = field(default_factory=dict)


class PositionSupervisor(PositionCapGuardMixin, AdverseRadarMixin, BinanceSmartDefenseMixin):
    """
    多用户版 position_supervisor_binance.py
    TV 军师指挥价格/regime → VPS 自主执行仓位管理、止盈网格、雷达锁润、先平后开、单向持仓。
    """

    def __init__(
        self,
        user_id: int,
        client: BinanceClient,
        initial_principal: float = 0.0,
        on_log: Optional[Callable] = None,
        on_trade_open: Optional[Callable] = None,
        on_trade_close: Optional[Callable] = None,
        on_trade_update_targets: Optional[Callable] = None,
        on_alert: Optional[Callable] = None,
    ):
        self.user_id = user_id
        self.client = client
        self.initial_principal = float(initial_principal or 0)
        self.position_manager = PositionManager(client)
        self.on_log = on_log or (lambda *a, **k: None)
        self.on_trade_open = on_trade_open or (lambda *a, **k: None)
        self.on_trade_close = on_trade_close or (lambda *a, **k: None)
        self.on_trade_update_targets = on_trade_update_targets or (lambda *a, **k: None)
        self.on_alert = on_alert or (lambda *a, **k: None)
        self._sentinel_error_notified = False

        self.symbol = getattr(client, "trading_symbol", settings.SYMBOL)
        self.exchange_id = getattr(client, "exchange_id", "binance")
        self.leverage = int(getattr(client, "trading_leverage", settings.LEVERAGE))
        self.monitoring = False
        self._lock = threading.Lock()
        self._signal_queue: queue.Queue[_QueuedSignal] = queue.Queue()
        self._queue_worker_lock = threading.Lock()
        self._queue_worker_started = False
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
        self.consumed_tp_levels: list[int] = []
        self._scan_ticks = 0
        self._init_adverse_radar_fields()

        os.makedirs("state", exist_ok=True)
        self.state_file = f"state/user_{user_id}.json"
        self._load_state()
        self._start_idle_flat_patrol()

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
                    "initial_qty": self.initial_qty,
                    "consumed_tp_levels": self.consumed_tp_levels,
                    "adverse_sl_armed": self.adverse_sl_armed,
                    "adverse_sl_prices": self.adverse_sl_prices,
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
                    self.regime = clamp_regime(s.get("regime", 3))
                    self.current_atr = float(s.get("current_atr", 30) or 30)
                    self.monitoring = bool(s.get("monitoring", False))
                    self.initial_qty = float(s.get("initial_qty", 0) or 0)
                    self.tv_tps = normalize_tv_targets(s.get("tv_tps", [0.0, 0.0, 0.0]))
                    self.consumed_tp_levels = [
                        int(x) for x in (s.get("consumed_tp_levels") or []) if int(x) in (1, 2, 3)
                    ]
                    self.adverse_sl_armed = bool(s.get("adverse_sl_armed", False))
                    self.adverse_sl_prices = [
                        float(x) for x in (s.get("adverse_sl_prices") or [])
                    ]
        except Exception as e:
            logger.error(f"[User {self.user_id}] load state failed: {e}")

    def _ensure_queue_worker(self) -> None:
        with self._queue_worker_lock:
            if self._queue_worker_started:
                return
            threading.Thread(
                target=self._signal_queue_worker,
                daemon=True,
                name=f"signal-queue-u{self.user_id}",
            ).start()
            self._queue_worker_started = True

    def _signal_queue_worker(self) -> None:
        while True:
            item = self._signal_queue.get()
            try:
                item.result = self._process_queued_signal(item)
            finally:
                item.event.set()
                self._signal_queue.task_done()

    def _process_queued_signal(self, item: _QueuedSignal) -> dict:
        deadline = item.enqueued_at + SIGNAL_QUEUE_TTL
        action = str(item.payload.get("action", "")).upper()

        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            if self._lock.acquire(timeout=min(SIGNAL_LOCK_SLICE, remaining)):
                try:
                    return self._execute_signal(item.payload)
                except Exception as e:
                    return {"status": "error", "message": str(e)}
                finally:
                    self._lock.release()

        queue_wait_ms = max(1, int((time.time() - item.enqueued_at) * 1000))
        lock_detail = {
            "action": action,
            "reason": "lock_timeout",
            "queue_wait_ms": queue_wait_ms,
            "queue_ttl_sec": SIGNAL_QUEUE_TTL,
        }
        self._log(
            "LOCK_TIMEOUT",
            f"信号队列 {SIGNAL_QUEUE_TTL:.0f}s 内未获得锁 [{action}]",
            lock_detail,
        )
        self._alert(
            "warning",
            "LOCK_TIMEOUT",
            "信号队列超时",
            f"用户 {self.user_id} {SIGNAL_QUEUE_TTL:.0f}s 内未能执行 [{action}]",
            lock_detail,
        )
        return {"status": "skipped", "reason": "lock_timeout", "queue_wait_ms": queue_wait_ms}

    def handle_signal(self, payload: dict) -> dict:
        raw_action = str(payload.get("action", "")).upper().strip()
        if not raw_action:
            return {"status": "skipped", "reason": "empty_action"}

        self._ensure_queue_worker()
        item = _QueuedSignal(payload=dict(payload), enqueued_at=time.time())
        self._signal_queue.put(item)

        if not item.event.wait(timeout=SIGNAL_QUEUE_TTL + 30):
            return {"status": "skipped", "reason": "queue_wait_timeout"}
        return item.result or {"status": "skipped", "reason": "empty_result"}

    def _execute_signal(self, payload: dict) -> dict:
        raw_action = str(payload.get("action", "")).upper()
        held_regime = self.regime
        held_atr = self.current_atr
        prev_tv_tps = list(self.tv_tps)
        self.regime = int(payload.get("regime", 3))
        self.regime = clamp_regime(self.regime)

        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_price = round_price(payload.get("price", 0))
        self.tv_tps = normalize_tv_targets([
            payload.get("tv_tp1", 0),
            payload.get("tv_tp2", 0),
            payload.get("tv_tp3", 0),
        ])
        self.risk_multiplier = float(payload.get("risk_multiplier", 1.0))
        close_reason = payload.get("reason", "策略指标反转/波动率安全退出")
        tv_side = str(payload.get("side") or "").upper().strip() or None
        tv_pnl_pct = payload.get("pnl_pct")
        if tv_pnl_pct is not None:
            try:
                tv_pnl_pct = float(tv_pnl_pct)
            except (TypeError, ValueError):
                tv_pnl_pct = None

        self.monitoring = False
        if raw_action == "CLOSE_PROTECT" or raw_action.startswith("CLOSE_PROTECT"):
            self._close_all(
                f"🛡️ 保护性全平：{close_reason}",
                tv_side=tv_side,
                tv_pnl_pct=tv_pnl_pct,
                close_action=raw_action,
            )
            return {"status": "ok", "action": raw_action, "detail": {"type": "close_protect"}}
        if raw_action == "CLOSE_TP3":
            self._close_all(
                "🎯 完美胜利：大趋势吃满，TP3 终极收网",
                tv_side=tv_side,
                tv_pnl_pct=tv_pnl_pct,
                close_action=raw_action,
            )
            return {"status": "ok", "action": raw_action, "detail": {"type": "close_tp3"}}
        if raw_action == "CLOSE":
            self._close_all(
                f"🧹 换防清场：{close_reason}",
                tv_side=tv_side,
                tv_pnl_pct=tv_pnl_pct,
                close_action=raw_action,
            )
            return {"status": "ok", "action": raw_action, "detail": {"type": "close"}}
        if raw_action in ["LONG", "SHORT"]:
            self.last_tv_side = raw_action
            self._save_state()
            return self._handle_smart_entry(
                raw_action,
                held_regime=held_regime,
                held_atr=held_atr,
                prev_tv_tps=prev_tv_tps,
            )
        return {"status": "skipped", "reason": "unknown_action", "detail": {"action": raw_action}}

    def _handle_smart_entry(
        self,
        action: str,
        *,
        held_regime: int | None = None,
        held_atr: float | None = None,
        prev_tv_tps: list | None = None,
    ) -> dict:
        threshold = float(settings.SAME_DIR_IGNORE_PRICE_DIFF_PCT)
        held_regime = held_regime if held_regime is not None else self.regime
        held_atr = float(held_atr if held_atr is not None else self.current_atr)

        pos = self.position_manager.get_position(self.symbol)
        has_pos = bool(pos and float(pos.get("positionAmt", 0)) != 0)
        current_side = None
        entry_price = float(self.watched_entry or 0)
        if has_pos:
            amt = float(pos["positionAmt"])
            current_side = "LONG" if amt > 0 else "SHORT"
            entry_price = float(pos.get("entryPrice") or entry_price or 0)

        curr_px = self.client.get_current_price(self.symbol)
        if curr_px <= 0:
            return {"status": "error", "reason": "price_unavailable", "message": "无法获取当前价格"}

        tv_price = float(self.tv_price or curr_px)
        if has_pos and current_side == action:
            ev = evaluate_same_direction(
                has_position=True,
                current_side=current_side,
                signal_side=action,
                entry_price=entry_price,
                tv_price=tv_price,
                mark_price=curr_px,
                held_regime=held_regime,
                new_regime=self.regime,
                held_atr=held_atr,
                new_atr=self.current_atr,
                threshold_pct=threshold,
            )
            if ev.action == SameDirAction.REFRESH_TPS:
                return self._refresh_same_direction_tps(
                    action, entry_price, ev, prev_tv_tps=prev_tv_tps or []
                )
            return self._close_then_open_entry(action, curr_px, ev)

        if has_pos and current_side != action:
            self._log("SIGNAL", f"⚡ 收到建仓信号 [{action}]，反方向先平后开")
            self.client.cancel_all_open_orders(self.symbol)
            time.sleep(0.5)
            self._close_all("反方向指令到达，触发【先平后开】原子对冲换防")
            if not self._wait_until_flat():
                self._log("ERROR", "反方向平仓后仍未归零，暂缓新开仓")
                return {"status": "error", "reason": "flat_timeout", "message": "平仓未确认归零"}
            self.client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4)
            return self._open_position(action, curr_px)

        return self._open_position(action, curr_px)

    def _close_then_open_entry(self, action: str, curr_px: float, ev) -> dict:
        threshold = float(settings.SAME_DIR_IGNORE_PRICE_DIFF_PCT)
        reason = format_reopen_reason(ev, threshold)
        self._log("SIGNAL", f"⚡ 收到建仓信号 [{action}]，{reason}")
        theme = resolve_exchange_theme(self.exchange_id)
        detail = {
            "exchange": self.exchange_id,
            "side": action,
            "entry": ev.entry_price,
            "tv_price": ev.tv_price,
            "price_diff_pct": round(ev.price_diff_pct, 4),
            "threshold_pct": threshold,
            "held_regime": ev.held_regime,
            "new_regime": ev.new_regime,
            "held_atr": ev.held_atr,
            "new_atr": ev.new_atr,
            "atr_changed": ev.atr_changed,
            "regime_changed": ev.regime_changed,
            "decision": ev.reason,
            "tv_tps": list(self.tv_tps),
        }
        self._alert(
            "info",
            "SAME_DIR_REOPEN",
            f"{theme['accent']} 同向换仓 · {theme['label']}",
            reason,
            detail,
        )
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        self._close_all("同方向新指令到达，触发【先平后开】洗清旧阵地")
        if not self._wait_until_flat():
            self._log("ERROR", "同向换仓平仓后仍未归零，暂缓新开仓")
            return {"status": "error", "reason": "flat_timeout", "message": "平仓未确认归零"}
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.4)
        return self._open_position(action, curr_px)

    def _refresh_same_direction_tps(
        self,
        action: str,
        entry_price: float,
        ev,
        *,
        prev_tv_tps: list,
    ) -> dict:
        pos = self._get_active_position()
        if not pos:
            return {"status": "error", "reason": "no_position", "message": "同向止盈更新时无持仓"}

        real_qty = float(pos["size"])
        self.current_side = action
        self.watched_qty = real_qty
        self.watched_entry = entry_price
        self.monitoring = True
        self._ensure_price_ws()

        theme = resolve_exchange_theme(self.exchange_id)
        threshold = float(settings.SAME_DIR_IGNORE_PRICE_DIFF_PCT)
        detail = {
            "exchange": self.exchange_id,
            "side": action,
            "entry": entry_price,
            "tv_price": ev.tv_price,
            "price_diff_pct": round(ev.price_diff_pct, 4),
            "threshold_pct": threshold,
            "held_regime": ev.held_regime,
            "new_regime": ev.new_regime,
            "held_atr": ev.held_atr,
            "new_atr": ev.new_atr,
            "atr_changed": ev.atr_changed,
            "regime_changed": ev.regime_changed,
            "decision": ev.reason,
            "old_tv_tps": list(prev_tv_tps),
            "new_tv_tps": list(self.tv_tps),
        }
        msg = (
            f"{format_refresh_reason(ev, threshold)} "
            f"{prev_tv_tps} → {self.tv_tps}"
        )
        self._log("SAME_DIR_TP_REFRESH", msg, detail)
        self._alert(
            "info",
            "SAME_DIR_TP_REFRESH",
            f"{theme['accent']} 同向智能持仓 · {theme['label']}",
            msg,
            detail,
        )
        if self.current_trade_id:
            self.on_trade_update_targets(
                self.current_trade_id,
                tv_tps=list(self.tv_tps),
                regime=self.regime,
                atr=self.current_atr,
            )

        dynamic_sl = self._radar_sl_to_pass()
        heal = self._rebuild_defenses(real_qty, entry_price, dynamic_sl=dynamic_sl)
        self._save_state()
        return {
            "status": "ok",
            "action": action,
            "detail": {
                "type": "same_dir_tp_refresh",
                "heal": heal,
                **detail,
            },
        }

    def _open_position(self, action: str, curr_px: float) -> dict:
        balance = self.client.get_available_balance()
        margin_pct = self.regime_settings[self.regime]["margin"] * self.risk_multiplier
        self.client.set_leverage(self.symbol, leverage=self.leverage)
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.4)
        qty, sizing_meta = compute_eth_qty(
            live_balance=balance,
            initial_principal=self.initial_principal,
            margin_pct=margin_pct,
            leverage=self.leverage,
            price=curr_px,
            round_fn=round_quantity,
        )
        if qty <= 0:
            self._log("ERROR", "余额不足，无法开仓")
            self._alert("warning", "INSUFFICIENT_BALANCE", "余额不足", f"用户 {self.user_id} 无法开仓")
            return {"status": "error", "reason": "insufficient_balance", "message": "余额不足，无法开仓"}

        open_side = "BUY" if action == "LONG" else "SELL"
        self._log(
            "SIGNAL",
            f"🚀 [唯一主仓] 极速开仓: {open_side} {qty} 个ETH | 档位 {self.regime} | "
            f"保证金 {sizing_meta['margin_usd']}U ({sizing_meta['sizing_source']})",
        )
        self.client.place_market_order(action, qty, self.symbol)
        time.sleep(2.0)

        pos = self.position_manager.get_position(self.symbol)
        if pos and float(pos.get("positionAmt", 0)) != 0:
            self.current_side = action
            real_qty = abs(float(pos["positionAmt"]))
            entry_price = float(pos["entryPrice"])
            cap_px = self.client.get_current_price(self.symbol) or curr_px
            cap_result = self._enforce_regime_cap_alignment(
                real_qty, entry_price, cap_px, reason="开仓后叠仓核验",
            )
            if cap_result.get("new_qty"):
                real_qty = float(cap_result["new_qty"])
            self.initial_qty = real_qty
            self.consumed_tp_levels = []
            self.current_trade_id = self.on_trade_open(
                self.user_id, action, real_qty, entry_price, self.regime, self.tv_tps
            )
            self.trade_opened_at = time.time()
            slip = (entry_price - self.tv_price) if action == "LONG" else (self.tv_price - entry_price)
            theme = resolve_exchange_theme(self.exchange_id)
            detail = {
                "exchange": self.exchange_id,
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
                **sizing_meta,
            }
            open_title = f"{theme['accent']} GEMINI开仓 · {theme['label']} 档位{self.regime}"
            self._log("OPEN", f"🔶 战神出击：{action} {real_qty} ETH @ {entry_price} | 滑点 {slip:+.2f}", detail)
            self._alert(
                "info", "OPEN",
                open_title,
                f"{action} {real_qty} ETH @ {entry_price} | 滑点 {slip:+.2f} | TP {self.tv_tps} | ATR {self.current_atr} | {theme['leverage']}×",
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

    def _close_order_side(self) -> str:
        """Binance order side to flatten current position."""
        return "SELL" if self.current_side == "LONG" else "BUY"

    def _compute_tp_slices(
        self, qty: float, exclude_levels: set[int] | None = None
    ) -> list[tuple[int, float, float]]:
        """按 regime 比例为当前头寸切 TP 份；已成交档位跳过并重归一化剩余比例。"""
        exclude_levels = exclude_levels or set()
        ratios = self.regime_settings[self.regime]["ratios"]
        active: list[tuple[int, float, float]] = []
        for i, ratio in enumerate(ratios):
            level = i + 1
            price = self.tv_tps[i]
            if level in exclude_levels or price <= 0:
                continue
            active.append((level, ratio, price))
        if not active or qty <= 0:
            return []

        total_ratio = sum(r for _, r, _ in active)
        slices: list[tuple[int, float, float]] = []
        allocated = 0.0
        for idx, (level, ratio, price) in enumerate(active):
            if idx == len(active) - 1:
                part_qty = round_quantity(qty - allocated)
            else:
                part_qty = round_quantity(qty * (ratio / total_ratio))
                allocated += part_qty
            if part_qty > 0:
                slices.append((level, part_qty, price))
        return slices

    def _infer_filled_tp_levels(self, qty: float, curr_px: float) -> set[int]:
        """推断已成交 TP 档位（state 记录 + 价格越过且无挂单）。"""
        filled = set(self.consumed_tp_levels or [])
        if curr_px <= 0:
            return filled

        probe = self._compute_tp_slices(qty, exclude_levels=set())
        scan = self._scan_open_defenses(probe, None)
        open_levels = {m["level"] for m in scan.get("matched_tps", [])}

        for level, _slice_qty, price in probe:
            if level in filled or level in open_levels or price <= 0:
                continue
            crossed = (
                (self.current_side == "LONG" and curr_px >= price)
                or (self.current_side == "SHORT" and curr_px <= price)
            )
            if crossed:
                filled.add(level)
        return filled

    def _active_tp_exclude_levels(self, qty: float, curr_px: float) -> set[int]:
        return self._infer_filled_tp_levels(qty, curr_px)

    def _classify_qty_change(self, old_qty: float, new_qty: float) -> str:
        if new_qty <= 0:
            return "full_close"
        if new_qty > old_qty + 0.001:
            return "manual_add"
        reduced = old_qty - new_qty
        if reduced <= 0.001:
            return "unchanged"
        old_slices = self._compute_tp_slices(
            old_qty, exclude_levels=set(self.consumed_tp_levels)
        )
        for level, slice_qty, _ in old_slices:
            if self._qty_matches(reduced, slice_qty):
                if level not in self.consumed_tp_levels:
                    self.consumed_tp_levels.append(level)
                return f"tp{level}_filled"
        return "manual_reduce"

    def _reconcile_radar_context(self, recovery: dict | None) -> dict:
        """重启：开仓日志 + 最新 TV + DB 交易 三方核实雷达参数。"""
        report: dict = {"sources": [], "warnings": list(recovery.get("checks") or []) if recovery else []}
        if not recovery:
            return report

        trade = recovery.get("trade") or {}
        open_log = recovery.get("open_log") or {}
        latest_tv = recovery.get("latest_tv") or {}

        if trade:
            report["sources"].append("db_trade")
            if not any(self.tv_tps) and trade.get("tv_tps"):
                self.tv_tps = normalize_tv_targets(trade["tv_tps"])
            if trade.get("regime"):
                self.regime = clamp_regime(trade["regime"])
            if trade.get("side") and not self.last_tv_side:
                self.last_tv_side = trade["side"]

        if open_log:
            report["sources"].append("open_log")
            report["open_log_side"] = open_log.get("side")
            report["open_log_qty"] = open_log.get("qty")
            report["open_log_entry"] = open_log.get("entry")
            if open_log.get("tv_tps"):
                self.tv_tps = normalize_tv_targets(open_log["tv_tps"])
            if open_log.get("regime"):
                self.regime = clamp_regime(open_log["regime"])
            if open_log.get("side"):
                self.last_tv_side = open_log["side"]
            if open_log.get("atr"):
                self.current_atr = float(open_log["atr"])

        if latest_tv:
            report["sources"].append("latest_tv")
            report["latest_tv_action"] = latest_tv.get("action")
            report["latest_tv_at"] = latest_tv.get("created_at")
            tv_action = (latest_tv.get("action") or "").upper()
            if tv_action in ("LONG", "SHORT"):
                self.last_tv_side = tv_action
                if any(latest_tv.get("tv_tps") or []):
                    self.tv_tps = normalize_tv_targets(latest_tv["tv_tps"])
                if latest_tv.get("regime"):
                    self.regime = clamp_regime(latest_tv["regime"])
                if latest_tv.get("atr"):
                    self.current_atr = float(latest_tv["atr"])
            elif tv_action.startswith("CLOSE"):
                report["warnings"].append("tv_close_while_position")

        report["last_tv_side"] = self.last_tv_side
        report["tv_tps"] = list(self.tv_tps)
        report["regime"] = self.regime
        return report

    def _price_matches(self, a: float, b: float) -> bool:
        return abs(round_price(a) - round_price(b)) < MIN_SL_MOVE

    def _qty_matches(self, a: float, b: float) -> bool:
        return abs(round_quantity(a) - round_quantity(b)) < 0.0005

    def _place_limit_with_retry(
        self, close_side: str, qty: float, price: float, label: str
    ) -> dict:
        last_err = None
        for attempt in range(1, TP_RETRY_MAX + 1):
            order = self.client.place_limit_order(
                close_side, qty, price, self.symbol, reduce_only=True
            )
            if order:
                return {
                    "ok": True,
                    "label": label,
                    "order_id": order.get("orderId"),
                    "qty": round_quantity(qty),
                    "price": round_price(price),
                    "attempt": attempt,
                }
            last_err = f"{label} attempt {attempt}/{TP_RETRY_MAX} failed"
            logger.warning(f"[User {self.user_id}] {last_err} qty={qty} price={price}")
            if attempt < TP_RETRY_MAX:
                time.sleep(TP_RETRY_DELAY * attempt)
        return {
            "ok": False,
            "label": label,
            "qty": round_quantity(qty),
            "price": round_price(price),
            "attempts": TP_RETRY_MAX,
            "error": last_err,
        }

    def _place_stop_with_retry(self, close_side: str, stop_price: float) -> dict:
        stop_price = round_price(stop_price)
        last_err = None
        for attempt in range(1, TP_RETRY_MAX + 1):
            order = self.client.place_stop_market_order(close_side, stop_price, self.symbol)
            if order:
                return {
                    "ok": True,
                    "label": "SL",
                    "order_id": order.get("orderId"),
                    "stop_price": stop_price,
                    "attempt": attempt,
                }
            last_err = f"SL attempt {attempt}/{TP_RETRY_MAX} failed"
            logger.warning(f"[User {self.user_id}] {last_err} stop={stop_price}")
            if attempt < TP_RETRY_MAX:
                time.sleep(TP_RETRY_DELAY * attempt)
        return {
            "ok": False,
            "label": "SL",
            "stop_price": stop_price,
            "attempts": TP_RETRY_MAX,
            "error": last_err,
        }

    def _scan_open_defenses(
        self,
        slices: list[tuple[int, float, float]],
        dynamic_sl: float | None = None,
    ) -> dict:
        """Compare expected TP/SL grid with Binance open orders."""
        close_side = self._close_order_side()
        open_orders = self.client.get_open_orders(self.symbol) or []

        live_limits = []
        live_stops = []
        for o in open_orders:
            otype = (o.get("type") or "").upper()
            if otype == "LIMIT" and o.get("side") == close_side:
                live_limits.append({
                    "order_id": o.get("orderId"),
                    "price": round_price(o.get("price", 0)),
                    "qty": round_quantity(o.get("origQty", 0)),
                })
            elif otype in ("STOP_MARKET", "STOP") and o.get("side") == close_side:
                live_stops.append({
                    "order_id": o.get("orderId"),
                    "stop_price": round_price(o.get("stopPrice", 0)),
                })

        matched_tps = []
        missing_tps = []
        qty_mismatch_tps = []
        duplicate_tps = []
        for level, qty, price in slices:
            if qty <= 0 or price <= 0:
                continue
            at_price = [
                lo for lo in live_limits
                if self._price_matches(lo["price"], price)
            ]
            if len(at_price) > 1:
                duplicate_tps.append({
                    "level": level,
                    "price": round_price(price),
                    "expected_qty": qty,
                    "orders": at_price,
                })
            elif len(at_price) == 1:
                live = at_price[0]
                if self._qty_matches(live["qty"], qty):
                    matched_tps.append({"level": level, **live})
                else:
                    qty_mismatch_tps.append({
                        "level": level,
                        "price": round_price(price),
                        "expected_qty": qty,
                        "live_qty": live["qty"],
                        "order_id": live["order_id"],
                    })
            else:
                missing_tps.append({"level": level, "qty": qty, "price": round_price(price)})

        sl_live = live_stops[0] if live_stops else None
        missing_sl = False
        if dynamic_sl and dynamic_sl > 0:
            missing_sl = not any(
                self._price_matches(s["stop_price"], dynamic_sl) for s in live_stops
            )

        expected_prices = {round_price(p) for _, _, p in slices if p > 0}
        orphan_limits = [
            lo for lo in live_limits
            if not any(self._price_matches(lo["price"], ep) for ep in expected_prices)
        ]

        needs_rebuild = bool(qty_mismatch_tps or duplicate_tps or orphan_limits)
        aligned = not missing_tps and not missing_sl and not needs_rebuild

        return {
            "close_side": close_side,
            "live_limits": live_limits,
            "live_stops": live_stops,
            "matched_tps": matched_tps,
            "missing_tps": missing_tps,
            "qty_mismatch_tps": qty_mismatch_tps,
            "duplicate_tps": duplicate_tps,
            "orphan_limits": orphan_limits,
            "sl_expected": round_price(dynamic_sl) if dynamic_sl else None,
            "sl_live": sl_live,
            "missing_sl": missing_sl,
            "needs_rebuild": needs_rebuild,
            "aligned": aligned,
            "expected_tp_count": len([s for s in slices if s[1] > 0 and s[2] > 0]),
            "matched_tp_count": len(matched_tps),
        }

    def _summarize_defense_scan(
        self, scan: dict, slices: list[tuple[int, float, float]]
    ) -> str:
        """Human-readable TP alignment report (for logs / DingTalk)."""
        parts: list[str] = []
        matched = {m["level"]: m for m in scan.get("matched_tps", [])}
        missing = {m["level"]: m for m in scan.get("missing_tps", [])}
        dup_map = {d["level"]: d for d in scan.get("duplicate_tps", [])}
        mismatch = {m["level"]: m for m in scan.get("qty_mismatch_tps", [])}

        for level, qty, price in slices:
            if qty <= 0 or price <= 0:
                continue
            label = f"TP{level} ({qty} @ {round_price(price)})"
            if level in matched:
                parts.append(f"{label} ✓")
            elif level in dup_map:
                n = len(dup_map[level].get("orders", []))
                parts.append(f"{label} (duplicate ×{n})")
            elif level in mismatch:
                mm = mismatch[level]
                parts.append(
                    f"{label} (qty mismatch live={mm.get('live_qty')} want={qty})"
                )
            elif level in missing:
                parts.append(f"{label} (missing)")
            else:
                parts.append(f"{label} (unknown)")

        n_exp = scan.get("expected_tp_count", len(parts))
        n_ok = scan.get("matched_tp_count", len(matched))
        head = f"{n_ok}/{n_exp} TP aligned"
        return head + " | " + "; ".join(parts) if parts else head

    def _cancel_all_verified(self) -> dict:
        """Cancel all open orders; verify empty; fallback to per-order cancel."""
        cancelled_ids: list[int] = []
        for round_i in range(CANCEL_VERIFY_ROUNDS):
            open_orders = self.client.get_open_orders(self.symbol) or []
            if not open_orders:
                return {"ok": True, "rounds": round_i, "cancelled_ids": cancelled_ids}

            self.client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4 + round_i * 0.25)

            remaining = self.client.get_open_orders(self.symbol) or []
            if not remaining:
                return {"ok": True, "rounds": round_i + 1, "cancelled_ids": cancelled_ids}

            for order in remaining:
                oid = order.get("orderId")
                if oid and self.client.cancel_order(self.symbol, int(oid)):
                    cancelled_ids.append(int(oid))
            time.sleep(0.35)

        remaining = self.client.get_open_orders(self.symbol) or []
        return {
            "ok": not remaining,
            "rounds": CANCEL_VERIFY_ROUNDS,
            "remaining": len(remaining),
            "cancelled_ids": cancelled_ids,
        }

    def _place_all_defense_orders(
        self,
        slices: list[tuple[int, float, float]],
        dynamic_sl: float | None,
    ) -> tuple[list, list]:
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        placed: list = []
        failed: list = []
        for level, qty, price in slices:
            if qty <= 0 or price <= 0:
                continue
            result = self._place_limit_with_retry(close_side, qty, price, f"TP{level}")
            if result["ok"]:
                placed.append(result)
            else:
                failed.append(result)
        if dynamic_sl and dynamic_sl > 0:
            sl_result = self._place_stop_with_retry(close_side, dynamic_sl)
            if sl_result["ok"]:
                placed.append(sl_result)
            else:
                failed.append(sl_result)
        return placed, failed

    def _aggressive_heal_defenses(
        self,
        qty: float,
        entry: float,
        dynamic_sl: float | None,
        scan: dict,
        slices: list[tuple[int, float, float]],
        *,
        reason: str,
    ) -> dict:
        """
        智能撤销重挂：重复/缺失/比例错 → 验证清空全部挂单 → 按当前头寸全量重挂。
        （解决重启叠单、cancel 失败只告警不修复的问题）
        """
        before_summary = self._summarize_defense_scan(scan, slices)
        self._log(
            "DEFENSE_HEAL",
            f"🔧 [{reason}] 止盈未对齐，启动撤销重挂 | {before_summary}",
            {"scan": scan, "slices": [(l, q, p) for l, q, p in slices], "entry": entry, "qty": qty},
        )
        self._alert(
            "warning", "DEFENSE_HEAL",
            "重启接管后限价止盈未对齐 · 执行智能撤销重挂",
            before_summary,
            {"scan": scan, "reason": reason},
        )

        cancel_result = self._cancel_all_verified()
        placed: list = []
        failed: list = []
        post = scan

        for attempt in range(HEAL_PLACE_ROUNDS):
            if not cancel_result.get("ok"):
                cancel_result = self._cancel_all_verified()
            placed, failed = self._place_all_defense_orders(slices, dynamic_sl)
            time.sleep(0.5)
            post = self._scan_open_defenses(slices, dynamic_sl)
            if post.get("aligned") and not failed:
                break

        after_summary = self._summarize_defense_scan(post, slices)
        aligned = bool(post.get("aligned")) and not failed
        detail = {
            "entry": entry,
            "qty": qty,
            "regime": self.regime,
            "tv_tps": list(self.tv_tps),
            "reason": reason,
            "before_summary": before_summary,
            "after_summary": after_summary,
            "cancel": cancel_result,
            "placed": placed,
            "failed": failed,
            "live_audit": post,
            "aligned": aligned,
            "skipped": False,
            "healed": True,
        }

        if aligned:
            self._log("DEFENSE_HEAL", f"✅ 撤销重挂完成 | {after_summary}", detail)
            self._alert("info", "DEFENSE_HEAL_OK", "限价止盈已对齐", after_summary, detail)
        else:
            self._log("DEFENSE_HEAL", f"❌ 撤销重挂后仍不对齐 | {after_summary}", detail)
            self._alert(
                "critical", "DEFENSE_HEAL_FAIL",
                "撤销重挂后止盈仍不对齐",
                after_summary,
                detail,
            )

        self._save_state()
        return detail

    def _place_missing_defenses(
        self,
        qty: float,
        entry: float,
        dynamic_sl: float | None,
        scan: dict,
        slices: list[tuple[int, float, float]] | None = None,
    ) -> dict:
        """Only place TPs/SL that scan says are missing — never re-place matched levels."""
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        repaired = []
        failed = []

        for item in scan.get("missing_tps", []):
            label = f"TP{item['level']}"
            result = self._place_limit_with_retry(
                close_side, item["qty"], item["price"], label
            )
            if result["ok"]:
                repaired.append(result)
                self._log(
                    "TP_RETRY",
                    f"✅ 补挂 {label} 成功 @ {result['price']} qty={result['qty']}",
                    result,
                )
            else:
                failed.append(result)
                self._alert(
                    "warning", "TP_RETRY_FAIL",
                    f"止盈补挂失败 · {label}",
                    f"{label} @ {item['price']} qty={item['qty']} 重试 {TP_RETRY_MAX} 次仍失败",
                    result,
                )

        if scan.get("missing_sl") and dynamic_sl:
            sl_result = self._place_stop_with_retry(close_side, dynamic_sl)
            if sl_result["ok"]:
                repaired.append(sl_result)
                self._log(
                    "TP_RETRY",
                    f"✅ 补挂 SL 成功 @ {sl_result['stop_price']}",
                    sl_result,
                )
            else:
                failed.append(sl_result)
                self._alert(
                    "warning", "SL_RETRY_FAIL",
                    "止损补挂失败",
                    f"SL @ {dynamic_sl} 重试 {TP_RETRY_MAX} 次仍失败",
                    sl_result,
                )

        if slices is None:
            slices = self._compute_tp_slices(qty)
        post = self._scan_open_defenses(slices, dynamic_sl)
        detail = {
            "entry": entry,
            "qty": qty,
            "before": scan,
            "after": post,
            "repaired": repaired,
            "failed": failed,
            "aligned": post.get("aligned", False),
        }
        if repaired or failed or not scan.get("aligned"):
            status = "一致" if post["aligned"] and not failed else "已修复" if repaired else "异常"
            self._log(
                "DEFENSE_AUDIT",
                f"📋 防线实盘核实: {status} | 缺TP={len(scan.get('missing_tps', []))} "
                f"补挂={len(repaired)} 失败={len(failed)}",
                detail,
            )
        return detail

    def _ensure_defenses(
        self,
        qty: float,
        entry: float,
        dynamic_sl: float | None = None,
        *,
        force_rebuild: bool = False,
        curr_px: float | None = None,
    ) -> dict:
        """
        确保 TP/SL 与当前头寸比例一致。
        - 已对齐 → 跳过（不重复挂单）
        - 任何不对齐 / 强制重构 → 验证撤销 + 全量重挂（智能 heal）
        """
        if curr_px is None:
            curr_px = self.client.get_current_price(self.symbol)
        exclude = self._active_tp_exclude_levels(qty, curr_px)
        slices = self._compute_tp_slices(qty, exclude_levels=exclude)
        scan = self._scan_open_defenses(slices, dynamic_sl)

        if scan["aligned"] and not force_rebuild:
            detail = {
                "entry": entry,
                "qty": qty,
                "regime": self.regime,
                "tv_tps": list(self.tv_tps),
                "excluded_tp_levels": sorted(exclude),
                "skipped": True,
                "reason": "defenses_already_aligned",
                "live_audit": scan,
                "aligned": True,
                "summary": self._summarize_defense_scan(scan, slices),
            }
            self._log(
                "DEFENSE",
                f"🛡️ 防线核实 [实盘一致·跳过] {detail['summary']} "
                f"SL={'有' if scan.get('sl_live') else '无'}",
                detail,
            )
            return detail

        heal_reason = "force_rebuild" if force_rebuild else "misaligned"
        if scan.get("duplicate_tps"):
            heal_reason = "duplicate_tp_orders"
        elif scan.get("qty_mismatch_tps"):
            heal_reason = "tp_qty_mismatch"
        elif scan.get("missing_tps"):
            heal_reason = "missing_tp_orders"
        elif scan.get("orphan_limits"):
            heal_reason = "orphan_tp_orders"

        return self._aggressive_heal_defenses(
            qty, entry, dynamic_sl, scan, slices, reason=heal_reason
        )

    def _verify_and_repair_defenses(
        self, qty: float, entry: float, dynamic_sl: float | None = None
    ) -> dict:
        """哨兵轮询：先核实再补挂，已对齐则不动作。"""
        return self._ensure_defenses(qty, entry, dynamic_sl, force_rebuild=False)

    def _protect_and_monitor(self, qty: float, entry_price: float):
        self._reset_adverse_radar()
        self.current_sl = entry_price
        self.best_price = entry_price
        self.watched_qty = qty
        self.watched_entry = entry_price
        self.monitoring = True
        self._ensure_price_ws()
        pos = self._get_active_position()
        if pos:
            result = self._smart_realign_defenses(
                pos["size"],
                pos["entry_price"],
                reason="开仓后智能防线对齐",
            )
            summary = self._format_audit_summary(result["audit"])
            self._log(
                "DEFENSE",
                f"🛡️ 开仓防线核查 {result['matched']}/{result['expected']} | {summary}",
                result,
            )
            if result["expected"] > 0 and result["matched"] < result["expected"]:
                self._alert(
                    "warning",
                    "DEFENSE",
                    "开仓后限价止盈未全部挂上",
                    f"{self.current_side} {pos['size']} ETH | 仅 {result['matched']}/{result['expected']} 档 | {summary}",
                    result,
                )
        self._save_state()
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _breakeven_sl_active(self) -> bool:
        """保本/锁润止损已激活（SL 越过入场价）。"""
        if not self.watched_entry or not self.current_sl:
            return False
        if self.current_side == "LONG":
            return self.current_sl > self.watched_entry
        if self.current_side == "SHORT":
            return self.current_sl < self.watched_entry
        return False

    def _ensure_price_ws(self) -> None:
        if hasattr(self.client, "start_public_price_ws"):
            self.client.start_public_price_ws(self.symbol)

    def _get_active_position(self) -> dict | None:
        pos = self.position_manager.get_position(self.symbol)
        if not pos or float(pos.get("positionAmt", 0)) == 0:
            return None
        amt = float(pos["positionAmt"])
        return {
            "size": abs(amt),
            "entry_price": float(pos.get("entryPrice", 0)),
            "side": "LONG" if amt > 0 else "SHORT",
        }

    def _wait_until_flat(self, timeout: float = FLAT_WAIT_TIMEOUT, poll: float = FLAT_WAIT_POLL) -> bool:
        """确认交易所持仓归零后再新开，避免残仓叠加。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            pos = self._get_active_position()
            if not pos or pos["size"] <= 0:
                return True
            time.sleep(poll)
        pos = self._get_active_position()
        return not pos or pos["size"] <= 0

    def _is_dust_qty(self, qty: float) -> bool:
        try:
            q = float(qty)
        except (TypeError, ValueError):
            return False
        return 0 < q <= DUST_QTY_ETH

    def _should_finalize_tp_victory(self, real_amt: float) -> bool:
        if real_amt <= 0:
            return False
        if self._is_dust_qty(real_amt):
            return True
        if self._collect_limit_tp_prices():
            return False
        ref = self.initial_qty or self.watched_qty
        if ref > 0 and real_amt <= ref * TP_COMPLETE_RESIDUAL_RATIO:
            return True
        return False

    def _confirm_exchange_flat(self, polls: int = FLAT_CONFIRM_POLLS, delay: float = FLAT_CONFIRM_DELAY) -> bool:
        """Require consecutive zero-amt reads to avoid transient API glitches."""
        for i in range(polls):
            pos = self.position_manager.get_position(self.symbol)
            amt = float(pos.get("positionAmt", 0)) if pos else 0.0
            if amt != 0:
                return False
            if i < polls - 1:
                time.sleep(delay)
        return True

    def _fetch_recent_tv_close(self) -> dict | None:
        try:
            from app.database import SessionLocal
            from app.services.radar_context import get_latest_tv_signal

            db = SessionLocal()
            try:
                tv = get_latest_tv_signal(db)
                if tv and str(tv.get("action") or "").upper().startswith("CLOSE"):
                    return tv
            finally:
                db.close()
        except Exception as e:
            logger.debug("[User %s] fetch recent TV close failed: %s", self.user_id, e)
        return None

    def _diagnose_flat_close(self, trigger: str, had_position: bool, *, platform_market: bool = False) -> dict:
        return diagnose_flat_close(
            client=self.client,
            symbol=self.symbol,
            side=self.current_side,
            qty=float(self.watched_qty or 0),
            entry=float(self.watched_entry or 0),
            trade_opened_at=self.trade_opened_at,
            consumed_tp_levels=list(self.consumed_tp_levels or []),
            tv_tps=list(self.tv_tps or []),
            trigger=trigger,
            had_position_before_close=had_position,
            recent_tv_close=self._fetch_recent_tv_close(),
            radar_active=self._is_radar_active(),
            platform_initiated_market=platform_market,
        )

    def _record_trade_close(
        self,
        reason: str,
        exit_price: float,
        *,
        attribution: dict | None = None,
        close_action: str | None = None,
        tv_side: str | None = None,
        tv_pnl_pct: float | None = None,
        alert_sev: str = "info",
        extra_detail: dict | None = None,
    ) -> None:
        if not self.current_trade_id:
            return
        pnl = 0.0
        live_pnl_pct = None
        if self.watched_entry and exit_price:
            diff = exit_price - self.watched_entry
            if self.current_side == "SHORT":
                diff = -diff
            pnl = diff * float(self.watched_qty or 0)
            if self.watched_entry > 0:
                live_pnl_pct = round(diff / self.watched_entry * 100, 2)

        start_ms = int(self.trade_opened_at * 1000) if self.trade_opened_at else None
        funding_fee = self.client.get_funding_fees(self.symbol, start_ms)
        close_detail: dict = {
            "exit_price": exit_price,
            "pnl": round(pnl, 4),
            "funding_fee": funding_fee,
            "reason": reason,
            "regime": self.regime,
            "side": self.current_side,
            "qty": self.watched_qty,
            "entry": self.watched_entry,
        }
        if extra_detail:
            close_detail.update(extra_detail)
        if attribution:
            close_detail["close_trigger"] = attribution.get("close_trigger")
            close_detail["close_origin"] = attribution.get("close_origin")
            close_detail["close_actor"] = attribution.get("close_actor")
            close_detail["human_reason"] = attribution.get("human_reason")
            close_detail["attribution"] = attribution
        if close_action:
            close_detail["close_action"] = close_action
        if tv_side:
            close_detail["tv_side"] = tv_side
        if tv_pnl_pct is not None:
            close_detail["tv_pnl_pct"] = round(float(tv_pnl_pct), 2)
        if live_pnl_pct is not None:
            close_detail["live_pnl_pct"] = live_pnl_pct
        if tv_pnl_pct is not None and live_pnl_pct is not None:
            close_detail["pnl_pct_delta"] = round(live_pnl_pct - float(tv_pnl_pct), 2)
        if tv_side and self.current_side and tv_side != self.current_side:
            close_detail["tv_side_mismatch"] = True
            self._log(
                "WARN",
                f"TV 方向 {tv_side} 与实盘 {self.current_side} 不一致（仍按实盘全平）",
                {"tv_side": tv_side, "live_side": self.current_side, "close_action": close_action},
            )

        self.on_trade_close(self.current_trade_id, exit_price, pnl, reason, funding_fee)
        close_detail["trade_id"] = self.current_trade_id
        self._log("CLOSE", reason, close_detail)
        alert_type = "CLOSE"
        if close_action:
            ca = str(close_action).upper()
            if "CLOSE_TP3" in ca:
                alert_type = "CLOSE_TP3"
            elif "CLOSE_PROTECT" in ca:
                alert_type = "CLOSE_PROTECT"
        self._alert(alert_sev, alert_type, "全平完成", reason, close_detail)
        if attribution and attribution.get("anomaly"):
            self._alert(
                "warning",
                "CLOSE_ANOMALY",
                "平仓原因待核实",
                attribution.get("human_reason") or reason,
                attribution,
            )

    def _handle_detected_flat(self, trigger: str = "sentinel_zero") -> bool:
        """Confirm flat, attribute cause, book-close, and detect false-flat / sync issues."""
        if not self._confirm_exchange_flat():
            self._log(
                "WARN",
                "哨兵归零检测未确认(可能瞬时读数)，继续监控",
                {"trigger": trigger, "watched_qty": self.watched_qty},
            )
            self._alert(
                "warning",
                "FLAT_UNCONFIRMED",
                "平仓检测未确认",
                "盘口瞬时出现零仓读数，已忽略并继续监控",
                {"trigger": trigger, "watched_qty": self.watched_qty},
            )
            return False

        pos_before = self.position_manager.get_position(self.symbol)
        had_position = bool(
            pos_before and float(pos_before.get("positionAmt", 0) or 0) != 0
        )
        attribution = self._diagnose_flat_close(trigger, had_position)
        reason = format_close_reason(attribution)
        self._close_all(reason, attribution=attribution, close_trigger=trigger)

        time.sleep(0.35)
        pos_after = self.position_manager.get_position(self.symbol)
        still_amt = float(pos_after.get("positionAmt", 0)) if pos_after else 0.0
        if still_amt != 0:
            side = "LONG" if still_amt > 0 else "SHORT"
            detail = {
                "still_amt": still_amt,
                "still_side": side,
                "trigger": trigger,
                "attribution": attribution,
            }
            self._alert(
                "critical",
                "FALSE_FLAT",
                "误判平仓 · 盘口仍有持仓",
                f"账本已收口但交易所仍显示 {side} {abs(still_amt)}，已尝试恢复监控",
                detail,
            )
            self.watched_qty = abs(still_amt)
            self.watched_entry = float(pos_after.get("entryPrice", 0) or self.watched_entry or 0)
            self.current_side = side
            self.monitoring = True
            self._save_state()
            threading.Thread(target=self._sentinel_loop, daemon=True).start()
            return False
        return True

    def _sweep_dust_and_finalize(self, reason: str) -> None:
        logger.warning(f"[User {self.user_id}] dust sweep → {reason}")
        self.monitoring = False
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.4)
        had_market_close = False
        for round_i in range(4):
            pos = self._get_active_position()
            if not pos or pos["size"] <= 0:
                break
            close_side = "SELL" if pos["side"] == "LONG" else "BUY"
            logger.info(
                f"[User {self.user_id}] dust round {round_i + 1}/4: {close_side} {pos['size']}"
            )
            self.client.place_market_order(close_side, pos["size"], reduce_only=True)
            had_market_close = True
            time.sleep(1.0)
        exit_price = self.client.get_current_price(self.symbol)
        attribution = self._diagnose_flat_close(
            "dust_sweep",
            had_position=had_market_close,
            platform_market=had_market_close,
        )
        close_reason = format_close_reason(attribution)
        self._record_trade_close(
            close_reason,
            exit_price,
            attribution=attribution,
            extra_detail={"swept_dust": True, "sweep_label": reason},
        )
        self.watched_qty = 0.0
        self.initial_qty = 0.0
        self.current_side = None
        self.consumed_tp_levels = []
        self.current_trade_id = None
        self.trade_opened_at = None
        self._save_state()
        self.client.cancel_all_open_orders(self.symbol)

    def _scan_and_sweep_dust_on_startup(self) -> bool:
        pos = self._get_active_position()
        if not pos or pos["size"] <= 0:
            return False
        if not self.current_side:
            self.current_side = pos["side"]
        if not self._is_dust_qty(pos["size"]) and not self._should_finalize_tp_victory(pos["size"]):
            return False
        reason = (
            "仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)"
            if (self.initial_qty > 0 or self.watched_qty > 0)
            else "重启扫描：盘口蚂蚁仓自动扫平"
        )
        self._sweep_dust_and_finalize(reason)
        return True

    def _recover_missed_flat_on_startup(self, was_monitoring: bool = False) -> bool:
        pos = self._get_active_position()
        if pos and pos["size"] > 0:
            return False
        prev_watched = float(self.watched_qty or 0)
        prev_side = self.current_side
        had_active = (
            prev_watched > 0
            or float(self.initial_qty or 0) > 0
            or prev_side in ("LONG", "SHORT")
            or was_monitoring
        )
        if not had_active:
            return False
        logger.warning(
            f"[User {self.user_id}] flat reconcile: book had {prev_watched} {prev_side}, exchange flat"
        )
        self.client.cancel_all_open_orders(self.symbol)
        self.monitoring = False
        exit_price = self.client.get_current_price(self.symbol)
        if not self.current_trade_id:
            try:
                from app.database import SessionLocal
                from app.models import Trade

                db = SessionLocal()
                try:
                    row = (
                        db.query(Trade)
                        .filter(Trade.user_id == self.user_id, Trade.status == "open")
                        .order_by(Trade.created_at.desc())
                        .first()
                    )
                    if row:
                        self.current_trade_id = row.id
                finally:
                    db.close()
            except Exception as e:
                logger.debug("[User %s] open trade lookup on flat recover: %s", self.user_id, e)
        attribution = self._diagnose_flat_close("startup_reconcile", had_position=False)
        close_reason = format_close_reason(attribution)
        self._record_trade_close(
            close_reason,
            exit_price,
            attribution=attribution,
            extra_detail={
                "prev_watched": prev_watched,
                "prev_side": prev_side,
                "flat_reconcile": True,
            },
        )
        self.watched_qty = 0.0
        self.initial_qty = 0.0
        self.current_side = None
        self.consumed_tp_levels = []
        self.current_trade_id = None
        self.trade_opened_at = None
        self._save_state()
        return True

    def _start_idle_flat_patrol(self) -> None:
        def loop():
            while True:
                time.sleep(30)
                if self.monitoring:
                    continue
                if not self._lock.acquire(timeout=2.0):
                    continue
                try:
                    if self.monitoring:
                        continue
                    pos = self._get_active_position()
                    if not pos or pos["size"] <= 0:
                        continue
                    if not self._is_dust_qty(pos["size"]) and not self._should_finalize_tp_victory(pos["size"]):
                        continue
                    if not self.current_side:
                        self.current_side = pos["side"]
                    self._sweep_dust_and_finalize("空闲巡检：盘口蚂蚁仓自动扫平")
                except Exception as exc:
                    logger.error(f"[User {self.user_id}] idle patrol: {exc}")
                finally:
                    self._lock.release()

        threading.Thread(target=loop, daemon=True, name=f"idle-patrol-u{self.user_id}").start()

    def _refresh_radar_state_on_recover(self, curr_px: float, entry: float) -> None:
        """重启：按现价恢复 best_price / 雷达激活 / 追踪止损位"""
        if curr_px <= 0 or not entry:
            return
        fee_buffer = entry * 0.0015
        trail_offset = self.current_atr * self.regime_settings[self.regime]["trail_offset"]

        if self.best_price == 0.0:
            self.best_price = entry
        if self.current_side == "LONG":
            self.best_price = max(self.best_price, curr_px)
        else:
            self.best_price = min(self.best_price, curr_px)

        progress = self._radar_activation_progress(curr_px)
        if progress >= 1.0:
            if self.current_side == "LONG":
                breakeven_floor = round_price(entry + fee_buffer)
                trail_sl = round_price(max(self.best_price - trail_offset, breakeven_floor))
                if not self._is_radar_active() or trail_sl > self.current_sl:
                    self.current_sl = max(self.current_sl or entry, trail_sl)
            else:
                breakeven_floor = round_price(entry - fee_buffer)
                trail_sl = round_price(min(self.best_price + trail_offset, breakeven_floor))
                if not self._is_radar_active() or trail_sl < self.current_sl:
                    self.current_sl = min(self.current_sl or entry, trail_sl)
            logger.info(
                f"[User {self.user_id}] 📡 重启雷达恢复: 进度 {progress:.0%} | "
                f"best={self.best_price:.2f} | SL={self.current_sl:.2f}"
            )
        elif self.current_sl == 0.0:
            self.current_sl = entry

    def _radar_activation_progress(self, curr_px: float) -> float:
        if curr_px <= 0 or not self.watched_entry:
            return 0.0
        tp1_dist = (
            abs(self.tv_tps[0] - self.watched_entry)
            if self.tv_tps[0] > 0
            else self.current_atr * 1.5
        )
        activation_ratio = self.regime_settings[self.regime]["activation"]
        if self.current_side == "LONG":
            required = self.watched_entry + tp1_dist * activation_ratio
            span = required - self.watched_entry
            if span <= 0:
                return 0.0
            return max(0.0, min(1.0, (curr_px - self.watched_entry) / span))
        required = self.watched_entry - tp1_dist * activation_ratio
        span = self.watched_entry - required
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (self.watched_entry - curr_px) / span))

    def _sentinel_poll_sec(self, curr_px: float = 0.0) -> float:
        if self._breakeven_sl_active():
            return SENTINEL_POLL_RADAR
        if curr_px > 0 and self._radar_activation_progress(curr_px) >= 0.5:
            return SENTINEL_POLL_ARMING
        return SENTINEL_POLL_NORMAL

    def _process_radar_trailing(self, real_amt: float, curr_px: float) -> bool:
        tp1_dist = (
            abs(self.tv_tps[0] - self.watched_entry)
            if self.tv_tps[0] > 0
            else self.current_atr * 1.5
        )
        cfg = self.regime_settings[self.regime]
        activation_ratio = cfg["activation"]
        trail_atr_multiplier = cfg["trail_offset"]
        if self.current_side == "LONG":
            required = self.watched_entry + tp1_dist * activation_ratio
            if curr_px < required:
                return False
        else:
            required = self.watched_entry - tp1_dist * activation_ratio
            if curr_px > required:
                return False

        trail_offset = self.current_atr * trail_atr_multiplier
        fee_buffer = self.watched_entry * 0.0015
        moved = False
        if self.current_side == "LONG":
            breakeven_floor = round_price(self.watched_entry + fee_buffer)
            new_sl = round_price(max(self.best_price - trail_offset, breakeven_floor))
            if new_sl > self.current_sl + RADAR_SL_MIN_MOVE:
                self.current_sl = new_sl
                self._save_state()
                sl_placed = self._realign_radar_defenses(real_amt, self.watched_entry, new_sl)
                trail_detail = {
                    "regime": self.regime,
                    "new_sl": new_sl,
                    "best_price": self.best_price,
                    "sl_placed": sl_placed,
                }
                self._log("TRAIL", f"雷达推升 SL → {new_sl}", trail_detail)
                self._alert("info", "TRAIL", "追踪雷达锁润", f"SL {new_sl}", trail_detail)
                moved = True
        else:
            breakeven_floor = round_price(self.watched_entry - fee_buffer)
            new_sl = round_price(min(self.best_price + trail_offset, breakeven_floor))
            if self.current_sl >= self.watched_entry or new_sl < self.current_sl - RADAR_SL_MIN_MOVE:
                self.current_sl = new_sl
                self._save_state()
                sl_placed = self._realign_radar_defenses(real_amt, self.watched_entry, new_sl)
                trail_detail = {
                    "regime": self.regime,
                    "new_sl": new_sl,
                    "best_price": self.best_price,
                    "sl_placed": sl_placed,
                }
                self._log("TRAIL", f"雷达下压 SL → {new_sl}", trail_detail)
                self._alert("info", "TRAIL", "追踪雷达锁润", f"SL {new_sl}", trail_detail)
                moved = True
        return moved

    def _sentinel_loop(self):
        last_px = 0.0
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
                            if self._handle_detected_flat("sentinel_zero"):
                                break
                        else:
                            break

                    if self.watched_qty > 0 and self._should_finalize_tp_victory(actual_qty):
                        self._sweep_dust_and_finalize(
                            "仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)"
                        )
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

                    curr_px = self.client.get_current_price(self.symbol)
                    if curr_px <= 0:
                        curr_px = last_px
                    else:
                        last_px = curr_px

                    entry_px = float(pos.get("entryPrice", 0) or self.watched_entry or 0)
                    cap_result = self._enforce_regime_cap_alignment(
                        actual_qty,
                        entry_px,
                        curr_px or entry_px,
                        reason="哨兵巡检",
                    )
                    if cap_result.get("trimmed", 0) > 0 and cap_result.get("new_qty"):
                        actual_qty = float(cap_result["new_qty"])
                        real_amt = actual_qty if actual_side == "LONG" else -actual_qty
                        self.watched_qty = actual_qty

                    qty_changed = abs(actual_qty - self.watched_qty) > 0.001
                    if qty_changed:
                        old_qty = self.watched_qty
                        change_type = self._classify_qty_change(old_qty, actual_qty)
                        self.watched_qty = actual_qty
                        self.watched_entry = float(pos["entryPrice"])
                        sl_to_pass = self._radar_sl_to_pass()

                        action_labels = {
                            "manual_add": "手动加仓",
                            "manual_reduce": "手动减仓",
                            "full_close": "人工全平",
                        }
                        action_msg = action_labels.get(
                            change_type,
                            f"部分止盈吃单 · {change_type}",
                        )
                        if change_type == "manual_add":
                            self.consumed_tp_levels = []

                        result = self._smart_realign_defenses(
                            actual_qty,
                            self.watched_entry,
                            dynamic_sl=sl_to_pass,
                            reason=f"人工异动: {action_msg}",
                        )

                        detail = {
                            "old_qty": old_qty,
                            "new_qty": actual_qty,
                            "entry": self.watched_entry,
                            "change_type": change_type,
                            "consumed_tp_levels": list(self.consumed_tp_levels),
                            "action_msg": action_msg,
                            "defense": result,
                        }
                        self._log(
                            "ADJUST",
                            f"🔄 智能感知仓位变化 [{change_type}]: {old_qty} ➔ {actual_qty} | "
                            f"TP {result['matched']}/{result['expected']}",
                            detail,
                        )
                        self._alert(
                            "warning", "MANUAL_ADJUST",
                            f"阵地异动 · {action_msg}",
                            f"数量 {old_qty} → {actual_qty} @ {self.watched_entry} | "
                            f"{self._format_audit_summary(result['audit'])}",
                            detail,
                        )
                        if result["expected"] > 0 and result["matched"] < result["expected"]:
                            self._alert(
                                "warning", "DEFENSE",
                                "人工异动后止盈未对齐",
                                self._format_audit_summary(result["audit"]),
                                result,
                            )
                        self._save_state()

                    self._scan_ticks += 1
                    if not qty_changed and self._scan_ticks % 10 == 0:
                        audit = self._audit_tp_levels(actual_qty)
                        if audit["issues"]:
                            logger.info(
                                f"[User {self.user_id}] 🔍 定期扫描发现异常: {audit['issues']}，触发智能补挂"
                            )
                            sl_to_pass = self._radar_sl_to_pass()
                            self._smart_realign_defenses(
                                actual_qty,
                                self.watched_entry,
                                dynamic_sl=sl_to_pass,
                                reason="定期防线扫描",
                            )

                    if curr_px > 0:
                        self.best_price = (
                            max(self.best_price, curr_px)
                            if self.current_side == "LONG"
                            else min(self.best_price, curr_px)
                        )
                        progress = self._radar_activation_progress(curr_px)
                        adverse_pct = self._adverse_move_pct(curr_px)
                        if self._is_radar_active() or progress >= 1.0:
                            if self.adverse_sl_armed:
                                self._disarm_adverse_staged_stops()
                            self._process_radar_trailing(actual_qty, curr_px)
                        elif adverse_pct >= ADVERSE_ARM_PCT or self.adverse_sl_armed:
                            self._process_adverse_radar_guard(actual_qty, curr_px, adverse_pct)
                        elif progress >= 0.5 and self._scan_ticks % 5 == 0:
                            logger.info(
                                f"[User {self.user_id}] 📡 雷达预热: 进度 {progress:.0%} | "
                                f"现价 {curr_px:.2f}"
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
            if self.monitoring:
                time.sleep(self._sentinel_poll_sec(last_px))

    def _rebuild_defenses(self, qty: float, entry: float, dynamic_sl=None) -> dict:
        """Cancel-all then rebuild — for trail update / manual qty change only."""
        return self._ensure_defenses(qty, entry, dynamic_sl, force_rebuild=True)

    def _close_all(
        self,
        reason: str = "",
        *,
        tv_side: str | None = None,
        tv_pnl_pct: float | None = None,
        close_action: str | None = None,
        attribution: dict | None = None,
        close_trigger: str | None = None,
    ):
        pos_before = self.position_manager.get_position(self.symbol)
        had_position = bool(
            pos_before and float(pos_before.get("positionAmt", 0) or 0) != 0
        )
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

        is_close_protect = bool(
            close_action and "CLOSE_PROTECT" in str(close_action).upper()
        )

        if reason and closed_successfully:
            if not had_position and is_close_protect:
                empty_detail: dict = {
                    "close_action": close_action,
                    "tv_side": tv_side,
                    "reason": reason,
                    "action": "cancel_orders_reset",
                }
                if tv_pnl_pct is not None:
                    empty_detail["tv_pnl_pct"] = round(float(tv_pnl_pct), 2)
                self._log(
                    "CLOSE_PROTECT_EMPTY",
                    f"🛡️ 空仓保护性全平：撤单复位（{reason.split('：', 1)[-1] if '：' in reason else reason}）",
                    empty_detail,
                )
                self._alert(
                    "info",
                    "CLOSE_PROTECT_EMPTY",
                    "空仓保护 · 撤单复位",
                    f"用户 {self.user_id} 实盘无持仓，已撤单并复位",
                    empty_detail,
                )
            elif self.current_trade_id:
                if attribution is None:
                    trigger = close_trigger or "code_close_all"
                    attribution = self._diagnose_flat_close(
                        trigger,
                        had_position,
                        platform_market=had_position,
                    )
                    reason = format_close_reason(attribution)
                sev = "critical" if "背离" in reason else "info"
                self._record_trade_close(
                    reason,
                    exit_price,
                    attribution=attribution,
                    close_action=close_action,
                    tv_side=tv_side,
                    tv_pnl_pct=tv_pnl_pct,
                    alert_sev=sev,
                )

        if closed_successfully and had_position:
            self._trigger_settlement_on_flat()

        self.monitoring = False
        self._disarm_adverse_staged_stops()
        self.watched_qty = 0.0
        self.initial_qty = 0.0
        self.consumed_tp_levels = []
        self.current_trade_id = None
        self.trade_opened_at = None
        self._save_state()
        self.client.cancel_all_open_orders(self.symbol)

    def _trigger_settlement_on_flat(self) -> None:
        """Profitable cycle awaiting flat: bill immediately after position closes."""
        try:
            from app.database import SessionLocal
            from app.models import User
            from app.services.settlement import try_settlement_on_flat

            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == self.user_id).first()
                if user:
                    settlement = try_settlement_on_flat(db, user)
                    if settlement:
                        logger.info(
                            "[User %s] settlement billed on flat: #%s payable=%.2f",
                            self.user_id, settlement.id, settlement.user_payable,
                        )
            finally:
                db.close()
        except Exception as e:
            logger.warning("[User %s] settlement-on-flat hook failed: %s", self.user_id, e)

    def recover_on_startup(
        self,
        open_trade_id: int | None = None,
        trade_context: dict | None = None,
        recovery_context: dict | None = None,
    ) -> dict:
        """VPS 自启：核实开仓日志+最新TV+实盘头寸，智能补挂止盈/续跑雷达。"""
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
            "best_price": self.best_price,
            "breakeven_active": False,
            "monitoring": False,
            "defenses_rebuilt": False,
            "defenses_skipped": False,
            "open_trade_id": open_trade_id,
        }
        try:
            self._load_state()
            saved_monitoring = self.monitoring

            if recovery_context is None and trade_context:
                recovery_context = {"trade": trade_context}

            if recovery_context:
                trade = recovery_context.get("trade") or {}
                if open_trade_id is None and trade.get("id"):
                    open_trade_id = trade["id"]
                    audit["open_trade_id"] = open_trade_id

            reconcile = self._reconcile_radar_context(recovery_context)
            audit.update(reconcile)

            if self._scan_and_sweep_dust_on_startup():
                audit["flat_reconcile"] = "dust_sweep"
                self.monitoring = False
                return audit
            if self._recover_missed_flat_on_startup(was_monitoring=saved_monitoring):
                audit["flat_reconcile"] = "missed_flat"
                self.monitoring = False
                return audit

            pos = self.position_manager.get_position(self.symbol)
            if not pos or float(pos.get("positionAmt", 0)) == 0:
                self.monitoring = False
                self._log("STARTUP", "VPS 自启审计：空仓待机", reconcile)
                return audit

            real_amt = float(pos["positionAmt"])
            self.current_side = "LONG" if real_amt > 0 else "SHORT"
            if not self.last_tv_side:
                self.last_tv_side = self.current_side

            self.watched_qty = abs(real_amt)
            saved_initial = float(self.initial_qty or 0)
            self.initial_qty = saved_initial if saved_initial > 0 else self.watched_qty
            self.watched_entry = float(pos["entryPrice"])
            self.current_trade_id = open_trade_id

            if self.best_price <= 0:
                self.best_price = self.watched_entry
            if self.current_sl <= 0:
                self.current_sl = self.watched_entry

            curr_px = self.client.get_current_price(self.symbol)
            self._refresh_radar_state_on_recover(curr_px, self.watched_entry)

            cap_result = self._enforce_regime_cap_alignment(
                self.watched_qty,
                self.watched_entry,
                curr_px or self.watched_entry,
                reason="重启恢复",
            )
            if cap_result.get("new_qty"):
                self.watched_qty = float(cap_result["new_qty"])
                if float(self.initial_qty or 0) > self.watched_qty:
                    self.initial_qty = self.watched_qty

            audit["direction_aligned"] = (
                self.current_side == self.last_tv_side if self.last_tv_side else True
            )
            if reconcile.get("warnings"):
                audit["radar_warnings"] = reconcile["warnings"]

            self.monitoring = True
            self._ensure_price_ws()

            sl_to_pass = self._radar_sl_to_pass()
            if cap_result.get("trimmed", 0) > 0 and cap_result.get("defense"):
                defense = cap_result["defense"]
            else:
                defense = self._smart_realign_defenses(
                    self.watched_qty,
                    self.watched_entry,
                    dynamic_sl=sl_to_pass,
                    reason="重启闪电接管",
                )

            audit.update({
                "has_position": True,
                "side": self.current_side,
                "qty": self.watched_qty,
                "entry": self.watched_entry,
                "last_tv_side": self.last_tv_side,
                "tv_tps": list(self.tv_tps),
                "current_sl": self.current_sl,
                "best_price": self.best_price,
                "breakeven_active": self._is_radar_active(),
                "consumed_tp_levels": list(self.consumed_tp_levels),
                "monitoring": True,
                "defenses_rebuilt": defense.get("rebuilt", False) or defense.get("healed", False),
                "defenses_skipped": defense.get("skipped", False),
                "defenses_aligned": defense.get("aligned", False),
                "defenses_healed": defense.get("healed", False) or defense.get("nuclear", False),
                "defense_summary": defense.get("after_summary") or defense.get("summary"),
                "tp_matched": defense.get("matched"),
                "tp_expected": defense.get("expected"),
            })
            self._save_state()
            threading.Thread(target=self._sentinel_loop, daemon=True).start()

            self._log(
                "STARTUP",
                f"雷达接管 {self.current_side} {self.watched_qty} @ {self.watched_entry} | "
                f"TV={self.last_tv_side} TP={self.tv_tps}",
                audit,
            )
            self._alert(
                "info", "STARTUP",
                "VPS 雷达智能接管完成",
                f"{self.current_side} {self.watched_qty} @ {self.watched_entry} | "
                f"{'防线就绪·未重复挂单' if defense.get('skipped') else '防线已智能补挂'}",
                audit,
            )
        except Exception as e:
            logger.error(f"[User {self.user_id}] recover failed: {e}")
            audit["error"] = str(e)
            self._log("STARTUP_FAIL", f"自启接管失败: {e}", audit)
            self._alert(
                "critical", "STARTUP_FAIL",
                "自启接管失败",
                str(e),
                audit,
            )
        return audit
