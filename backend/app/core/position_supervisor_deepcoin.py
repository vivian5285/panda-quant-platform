"""Deepcoin multi-user PositionSupervisor (Gemini P0)."""
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from app.core.deepcoin_client import DeepcoinClient, CLIENT_VERSION
from app.core.regime_utils import clamp_regime
from app.core.same_direction_policy import (
    SameDirAction,
    evaluate_same_direction,
    format_refresh_reason,
    format_reopen_reason,
)
from app.core.position_sizing import read_contract_equity
from app.core.tv_entry_sizing import (
    ENTRY_TYPES_ADD,
    parse_tv_entry_fields,
    resolve_vps_entry_qty_deepcoin,
)
from app.core.position_qty_tolerance import qty_change_significant
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
from app.core.tp_slice_guard import compute_tp_slices, infer_filled_tp_levels, match_qty_reduction_to_tp_level
from app.core.position_qty_tolerance import tp_slice_qty_tolerance
from app.core.position_cap_guard import PositionCapGuardMixin
from app.core.adverse_radar_guard import AdverseRadarMixin, ADVERSE_STOP_TOLERANCE
from app.core.startup_reconcile import StartupReconcileMixin, format_startup_defense_summary, recovery_section, apply_tv_sl_from_sources, adopt_live_tv_side
from app.config import get_settings
from app.services.trading_alerts import resolve_exchange_theme
from app.services.close_alert_utils import (
    build_close_detail,
    build_verify_note,
    extract_tv_close_fields,
    format_close_dingtalk_message,
    resolve_close_alert_title,
    resolve_close_alert_type,
)

logger = logging.getLogger(__name__)
settings = get_settings()

DEEPCOIN_SUPERVISOR_VERSION = "v13.4.6-flat-reconcile"
SENTINEL_POLL_NORMAL = 6
SENTINEL_POLL_ARMING = 3
SENTINEL_POLL_RADAR = 2
DUST_ORPHAN_CONTRACTS = 1
TP_COMPLETE_RESIDUAL_RATIO = 0.12
FLAT_WAIT_TIMEOUT = 12.0
FLAT_WAIT_POLL = 0.6


class _DingtalkBridge:
    """Route legacy dingtalk report_* calls to Gemini on_alert."""

    def __init__(self, supervisor: "DeepcoinPositionSupervisor"):
        self._sup = supervisor

    def __getattr__(self, name: str):
        def _call(*args, **kwargs):
            title = name.replace("report_", "").replace("_", " ").title()
            msg_parts = [str(a) for a in args if a is not None]
            message = " | ".join(msg_parts)[:500] if msg_parts else title
            severity = (
                "critical" if "fail" in name or "force" in name
                else "warning" if "alert" in name or "intervention" in name
                else "info"
            )
            detail = dict(kwargs) if kwargs else {}
            self._sup._alert(severity, name.upper(), title, message, detail)

        return _call

class DeepcoinPositionSupervisor(PositionCapGuardMixin, AdverseRadarMixin, StartupReconcileMixin):
    def __init__(
        self,
        user_id: int,
        client: DeepcoinClient,
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
        self.on_log = on_log or (lambda *a, **k: None)
        self.on_trade_open = on_trade_open or (lambda *a, **k: None)
        self.on_trade_close = on_trade_close or (lambda *a, **k: None)
        self.on_trade_update_targets = on_trade_update_targets or (lambda *a, **k: None)
        self.on_alert = on_alert or (lambda *a, **k: None)
        self._dt = _DingtalkBridge(self)
        self.current_trade_id: int | None = None
        self.exchange_id = "deepcoin"

        self.symbol = settings.DEEPCOIN_SYMBOL
        self.monitoring = False
        self._lock = threading.Lock()

        # 与币安完全一致的四档矩阵：activation=启动雷达的 TP1 距离比例，trail_offset=ATR 追踪倍数
        self.regime_settings = {
            1: {"margin": 0.15, "ratios": [0.25, 0.35, 0.40], "activation": 0.40, "trail_offset": 0.40},
            2: {"margin": 0.25, "ratios": [0.20, 0.35, 0.45], "activation": 0.50, "trail_offset": 0.60},
            3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
            4: {"margin": 0.50, "ratios": [0.05, 0.20, 0.75], "activation": 0.70, "trail_offset": 1.30},
        }
        self.leverage = int(getattr(client, "trading_leverage", settings.DEEPCOIN_LEVERAGE))
        self.face_value = 0.1

        self.regime = 3
        self.risk_multiplier = 1.0
        self.current_atr = 30.0
        self.best_price = 0.0
        self.current_sl = 0.0
        self.tv_price = 0.0
        self.tv_tps = [0.0, 0.0, 0.0]

        self.initial_qty = 0
        self.base_qty = 0
        self.add_count = 0
        self.consumed_tp_levels: list[int] = []
        self.watched_qty = 0
        self.watched_entry = 0.0
        self.current_side = None
        self.last_tv_side = None
        self.last_tv_signal = None
        self._scan_ticks = 0
        self._signal_queue = queue.Queue()
        self._signal_worker_started = False
        self._init_adverse_radar_fields()

        base_dir = os.path.join("data", "supervisor", f"deepcoin_{user_id}")
        os.makedirs(base_dir, exist_ok=True)
        self.state_file = os.path.join(base_dir, "state.json")
        self.tv_journal = os.path.join(base_dir, "tv_journal.jsonl")
        self.open_journal = os.path.join(base_dir, "open_journal.jsonl")

        logger.info(
            f"🧠 深币 Supervisor user={user_id} [{DEEPCOIN_SUPERVISOR_VERSION}/{CLIENT_VERSION}] 已加载"
        )
        self._start_signal_worker()
        self._start_idle_flat_patrol()

    def _start_idle_flat_patrol(self):
        """空仓待命时后台巡检：发现孤立残张 → 自动扫尾 + 钉钉"""
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
                    if not pos or self._safe_qty(pos.get("size")) <= 0:
                        continue
                    real_amt = self._safe_qty(pos["size"])
                    if not self._is_dust_qty(real_amt) and not self._should_finalize_tp_victory(real_amt):
                        continue
                    if not self.current_side:
                        self.current_side = "LONG" if pos.get("posSide") == "long" else "SHORT"
                    logger.warning(
                        f"🐜 [空闲巡检] 发现残量 {self.current_side} {real_amt}张 → 扫尾"
                    )
                    self._sweep_dust_and_finalize("重启扫描：盘口蚂蚁仓自动扫平")
                except Exception as e:
                    logger.error(f"空闲巡检异常: {e}")
                finally:
                    self._lock.release()

        threading.Thread(target=loop, daemon=True, name="idle-flat-patrol").start()

    def _log(self, event_type: str, message: str, detail: dict | None = None, trade_id: int | None = None):
        self.on_log(self.user_id, event_type, message, detail, trade_id)

    def _alert(
        self,
        severity: str,
        alert_type: str,
        title: str,
        message: str,
        detail: dict | None = None,
    ):
        self.on_alert(self.user_id, severity, alert_type, title, message, detail or {})

    @staticmethod
    def _call_dingtalk(fn, **kwargs):
        """兼容 VPS 旧版 self._dt.py（缺少 verified / swept_dust 等新参数）"""
        try:
            fn(**kwargs)
        except TypeError as exc:
            if "unexpected keyword argument" not in str(exc):
                raise
            legacy = {
                k: v for k, v in kwargs.items()
                if k not in ("verified", "swept_dust")
            }
            logger.warning(f"钉钉旧版降级播报 {getattr(fn, '__name__', 'dingtalk')}: {exc}")
            fn(**legacy)

    def _start_signal_worker(self):
        if self._signal_worker_started:
            return
        self._signal_worker_started = True
        threading.Thread(target=self._signal_worker_loop, daemon=True, name="tv-signal-worker").start()

    def _signal_worker_loop(self):
        while True:
            payload = self._signal_queue.get()
            try:
                self._process_signal(payload)
            except Exception as e:
                logger.error(f"❌ 信号处理异常: {e}", exc_info=True)
            finally:
                self._signal_queue.task_done()

    def enqueue_signal(self, payload):
        depth = self._signal_queue.qsize()
        action = (payload.get("action") or "?").upper()
        self._signal_queue.put(payload)
        logger.info(f"📬 TV信号入队: {action} | 队列深度 {depth + 1}")

    def signal_queue_depth(self):
        return self._signal_queue.qsize()

    def _append_journal(self, path, record):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        record = dict(record)
        record["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _load_last_journal_entry(self, path):
        if not os.path.exists(path):
            return None
        last = None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)
                    except json.JSONDecodeError:
                        continue
        return last

    def _record_tv_signal(self, payload, raw_action):
        entry = {
            "action": raw_action,
            "regime": self.regime,
            "atr": self.current_atr,
            "price": self.tv_price,
            "tv_tps": self.tv_tps,
            "reason": payload.get("reason", ""),
        }
        self.last_tv_signal = entry
        self._append_journal(self.tv_journal, entry)
        logger.info(
            f"📡 TV日志: {raw_action} R{self.regime} @ {self.tv_price:.2f} "
            f"TP={self.tv_tps}"
        )

    def _record_open_log(self, side, qty, entry, source="open"):
        self._append_journal(self.open_journal, {
            "source": source,
            "side": side,
            "qty": qty,
            "entry": entry,
            "regime": self.regime,
            "tv_tps": self.tv_tps,
            "tv_price": self.tv_price,
            "last_tv_side": self.last_tv_side,
        })

    def _load_last_tv_open_signal(self):
        """TV 日志中最近一条 LONG/SHORT（CLOSE 之后仍可用于方向对账）"""
        if not os.path.exists(self.tv_journal):
            return None
        last_open = None
        with open(self.tv_journal, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                action = (entry.get("action") or "").upper()
                if action in ("LONG", "SHORT"):
                    last_open = entry
        return last_open

    def _reconcile_context_on_recover(self, pos):
        """重启对账：实盘头寸 vs 账本 vs 最新 TV / 开仓日志"""
        notes = []
        reconcile = {
            "notes": notes,
            "tv_close": False,
            "direction_mismatch": False,
            "qty_manual_change": None,
        }
        side = "LONG" if pos.get("posSide") == "long" else "SHORT"
        real_amt = self._safe_qty(pos.get("size"))
        saved_watched = self._safe_qty(self.watched_qty)
        saved_initial = self._safe_qty(self.initial_qty)

        last_tv = self._load_last_journal_entry(self.tv_journal)
        last_open = self._load_last_journal_entry(self.open_journal)
        last_open_tv = self._load_last_tv_open_signal()

        if last_tv:
            self.last_tv_signal = last_tv
            tv_action = (last_tv.get("action") or "").upper()
            tv_tps_saved = self._sanitize_tp_prices(last_tv.get("tv_tps", []))
            tv_tp_count = sum(1 for t in tv_tps_saved if t > 0)

            if last_tv.get("regime"):
                self.regime = clamp_regime(last_tv["regime"])
            if last_tv.get("atr"):
                self.current_atr = float(last_tv["atr"])
            if self.tv_price <= 0 and float(last_tv.get("price", 0) or 0) > 0:
                self.tv_price = float(last_tv["price"])

            if tv_action in ("LONG", "SHORT"):
                self.last_tv_side = tv_action
                if tv_tp_count > 0:
                    self.tv_tps = tv_tps_saved
                    notes.append(f"TV日志同步止盈价 {self.tv_tps}")
                if side != tv_action:
                    reconcile["direction_mismatch"] = True
                    notes.append(
                        f"方向背离: 实盘{side} vs TV最新{tv_action} ({last_tv.get('ts', '')})"
                    )
            elif tv_action.startswith("CLOSE"):
                reconcile["tv_close"] = True
                notes.append(
                    f"TV最新为{tv_action} ({last_tv.get('ts', '')})，实盘仍有仓 → 应清场"
                )
                if last_open_tv:
                    self.last_tv_side = (last_open_tv.get("action") or "").upper()
                    open_tps = self._sanitize_tp_prices(last_open_tv.get("tv_tps", []))
                    if sum(1 for t in open_tps if t > 0) > 0:
                        self.tv_tps = open_tps

        if not self.last_tv_side and last_open_tv:
            self.last_tv_side = (last_open_tv.get("action") or "").upper()

        if last_open:
            open_side = last_open.get("side")
            open_qty = self._safe_qty(last_open.get("qty") or 0)
            if open_qty > 0:
                reconcile["open_log_qty"] = open_qty
            if open_side and side != open_side:
                notes.append(f"开仓日志方向 {open_side} ≠ 实盘 {side}")
            open_entry = float(last_open.get("entry", 0) or 0)
            entry = float(pos.get("entry_price", 0) or 0)
            if open_entry > 0 and abs(entry - open_entry) > 3.0:
                notes.append(f"入场偏差: 开仓日志 {open_entry:.2f} vs 实盘 {entry:.2f}")

        if saved_watched > 0 and saved_watched != real_amt:
            action_msg = (
                "手动加仓" if real_amt > saved_watched
                else "部分止盈吃单 / 手动减仓"
            )
            reconcile["qty_manual_change"] = (saved_watched, real_amt, action_msg)
            notes.append(f"人工异动(重启): {saved_watched}张 → {real_amt}张 ({action_msg})")

        if not self.last_tv_side:
            self.last_tv_side = side
        elif side != self.last_tv_side and not reconcile["tv_close"]:
            reconcile["direction_mismatch"] = True
            if not any("方向背离" in n for n in notes):
                notes.append(f"方向背离: 实盘{side} vs TV指令{self.last_tv_side}")

        if saved_initial <= 0 and real_amt > 0:
            self.initial_qty = real_amt

        for n in notes:
            logger.warning(f"🔎 重启对账: {n}")
        return reconcile

    @staticmethod
    def _sanitize_tp_prices(tp_list):
        """TV/状态文件里的浮点价统一规整到 2 位小数，避免 1517.4 触发 PriceNotOnTick"""
        out = []
        for t in tp_list:
            try:
                out.append(round(float(t), 2) if float(t) > 0 else 0.0)
            except (TypeError, ValueError):
                out.append(0.0)
        return out

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    "last_tv_side": self.last_tv_side,
                    "current_side": self.current_side,
                    "watched_qty": self.watched_qty,
                    "watched_entry": self.watched_entry,
                    "current_sl": self.current_sl,
                    "monitoring": self.monitoring,
                    "regime": self.regime,
                    "current_atr": self.current_atr,
                    "tv_tps": self.tv_tps,
                    "tv_price": self.tv_price,
                    "best_price": self.best_price,
                    "initial_qty": self.initial_qty,
                    "base_qty": float(getattr(self, "base_qty", 0) or 0),
                    "add_count": int(getattr(self, "add_count", 0) or 0),
                    "consumed_tp_levels": list(self.consumed_tp_levels),
                    "last_tv_signal": self.last_tv_signal,
                    "adverse_sl_armed": self.adverse_sl_armed,
                    "adverse_sl_prices": self.adverse_sl_prices,
                    "adverse_consumed_tiers": list(self.adverse_consumed_tiers),
                    "adverse_arm_dingtalk_sent": bool(getattr(self, "adverse_arm_dingtalk_sent", False)),
                    "adverse_last_repair_ts": float(getattr(self, "_adverse_last_repair_ts", 0) or 0),
                    "tv_sl": float(getattr(self, "tv_sl", 0) or 0),
                }, f)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    def _close_order_side(self) -> str:
        return "sell" if self.current_side == "LONG" else "buy"

    @staticmethod
    def _safe_qty(val, default=0):
        """Deepcoin API 常返回 '1.000000' 字符串，须先 float 再 int"""
        if val is None or val == "":
            return default
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default

    def _get_active_position(self):
        res = self.client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                if self._safe_qty(p.get("pos")) > 0:
                    return {
                        "size": self._safe_qty(p.get("pos")),
                        "entry_price": round(float(p.get("avgPx", p.get("price", 0)) or 0), 2),
                        "posSide": p.get("posSide", "long").lower(),
                    }
        return None

    def _verify_flat(self):
        pos = self._get_active_position()
        return pos is None or self._safe_qty(pos.get("size")) == 0

    def _wait_until_flat(self, timeout: float = FLAT_WAIT_TIMEOUT, poll: float = FLAT_WAIT_POLL) -> bool:
        """确认交易所持仓归零后再新开，避免残仓叠加。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._verify_flat():
                return True
            time.sleep(poll)
        return self._verify_flat()

    def _is_dust_qty(self, qty):
        """深币最小 1 张；无主仓账本时的孤立 1 张视为蚂蚁仓"""
        q = self._safe_qty(qty)
        if q <= 0:
            return False
        ref = self._safe_qty(self.initial_qty) + self._safe_qty(self.watched_qty)
        return q == DUST_ORPHAN_CONTRACTS and ref == 0

    def _should_finalize_tp_victory(self, real_amt):
        """止盈网格已吃完、盘口无 TP 限价单，但可能残留张数 → 扫尾收网"""
        real_amt = self._safe_qty(real_amt)
        if real_amt <= 0:
            return False
        if self._is_dust_qty(real_amt):
            return True
        if self._collect_limit_tp_prices():
            return False
        ref = self._safe_qty(self.initial_qty or self.watched_qty)
        if ref > 0:
            threshold = max(DUST_ORPHAN_CONTRACTS, int(ref * TP_COMPLETE_RESIDUAL_RATIO))
            if real_amt <= threshold:
                return True
        return False

    def _report_flat_close(
        self,
        reason,
        swept_dust=False,
        *,
        close_action: str | None = None,
        tv_close_ctx: dict | None = None,
        tv_side: str | None = None,
        tv_pnl_pct: float | None = None,
        tv_reason: str | None = None,
        entry_snapshot: float = 0.0,
        qty_snapshot: float = 0.0,
        side_snapshot: str | None = None,
        trade_id_snapshot: int | None = None,
    ):
        """平仓/止盈收网：REST 核查 → 实盘盈亏 → 钉钉全平警报（含 TV 明细字段）"""
        flat = self._wait_verify(self._verify_flat, retries=6, delay=0.5)
        exit_price = self.client.get_current_price(self.symbol) or 0.0
        display_reason = tv_reason or reason or "仓位归零 (人工全平 / 止盈吃满)"
        live_pnl_pct = None
        pnl = 0.0
        entry = float(entry_snapshot or 0)
        qty = float(qty_snapshot or 0)
        side = side_snapshot or self.current_side
        if entry > 0 and exit_price > 0:
            diff = exit_price - entry
            if side == "SHORT":
                diff = -diff
            pnl = diff * qty
            live_pnl_pct = round(diff / entry * 100, 2)

        verify_note = build_verify_note(
            exit_price=exit_price if exit_price > 0 else None,
            live_pnl_pct=live_pnl_pct,
            tv_pnl_pct=tv_pnl_pct,
            flat_confirmed=flat,
        )
        if swept_dust:
            verify_note = f"蚂蚁仓已市价扫尾 | {verify_note}"
        if not flat:
            pos = self._get_active_position()
            residual = self._safe_qty(pos["size"]) if pos else 0
            if residual > 0 and not self._is_dust_qty(residual):
                logger.warning(
                    f"平仓钉钉跳过：空仓核查未通过 | 残留 {residual}张 | reason={display_reason}"
                )
                return
            verify_note = f"{verify_note} | REST 同步略延迟"
            logger.info(f"平仓钉钉：REST 延迟，仍推送收网播报 | reason={display_reason}")

        close_detail = build_close_detail(
            exchange_id=self.exchange_id,
            side=side,
            qty=qty,
            entry=entry,
            regime=self.regime,
            atr=self.current_atr,
            exit_price=exit_price if exit_price > 0 else None,
            pnl=pnl,
            funding_fee=0.0,
            tv_fields=tv_close_ctx,
            close_action=close_action,
            tv_reason=display_reason,
            live_pnl_pct=live_pnl_pct,
            verify_note=verify_note,
            trade_id=trade_id_snapshot,
        )
        if tv_side:
            close_detail["tv_side"] = tv_side
        if tv_pnl_pct is not None:
            close_detail["tv_pnl_pct"] = round(float(tv_pnl_pct), 2)
        if tv_side and side and tv_side != side:
            close_detail["tv_side_mismatch"] = True

        tid = trade_id_snapshot or self.current_trade_id
        if tid and exit_price > 0:
            self.on_trade_close(tid, exit_price, pnl, display_reason, 0.0)

        alert_type = resolve_close_alert_type(close_action, display_reason)
        alert_title = resolve_close_alert_title(close_action, display_reason)
        ding_msg = format_close_dingtalk_message(display_reason, verify_note)
        self._log("CLOSE", display_reason, close_detail, trade_id=tid)
        self._alert("info", alert_type, alert_title, ding_msg, close_detail)

    def _sweep_dust_and_finalize(self, reason):
        """哨兵检测：止盈后蚂蚁仓/无 TP 残张 → 撤单 + reduceOnly 扫尾 + 收网钉钉"""
        logger.warning(f"🐜 止盈扫尾：检测到残量，启动蚂蚁仓强平 → {reason}")
        self.monitoring = False
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.4)
        for round_i in range(4):
            pos = self._get_active_position()
            if not pos or self._safe_qty(pos.get("size")) <= 0:
                break
            close_side = "sell" if pos["posSide"] == "long" else "buy"
            live_sz = self._safe_qty(pos["size"])
            logger.info(f"🐜 扫尾第 {round_i + 1}/4: {close_side} {live_sz}张 reduceOnly")
            self.client.place_market_order(
                self.symbol, close_side, pos["posSide"], live_sz, reduce_only=True,
            )
            time.sleep(1.0)
        self.watched_qty = 0
        self.initial_qty = 0
        self.base_qty = 0
        self.add_count = 0
        self.current_side = None
        self._save_state()
        self.client.cancel_all_open_orders(self.symbol)
        self._report_flat_close(reason, swept_dust=True)

    def _scan_and_sweep_dust_on_startup(self):
        """重启首检：发现蚂蚁仓/止盈残张 → 扫尾收网，避免误接管为正常持仓"""
        pos = self._get_active_position()
        if not pos or self._safe_qty(pos.get("size")) <= 0:
            return False
        if not self.current_side:
            self.current_side = "LONG" if pos.get("posSide") == "long" else "SHORT"
        real_amt = self._safe_qty(pos["size"])
        if not self._is_dust_qty(real_amt) and not self._should_finalize_tp_victory(real_amt):
            return False
        if self._safe_qty(self.initial_qty) > 0 or self._safe_qty(self.watched_qty) > 0:
            reason = "仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)"
        else:
            reason = "重启扫描：盘口蚂蚁仓自动扫平"
        logger.warning(
            f"🐜 [重启扫描] {self.current_side} 残量 {real_amt}张 "
            f"(initial={self.initial_qty}, watched={self.watched_qty}) → 扫尾强平"
        )
        self._sweep_dust_and_finalize(reason)
        return True

    def _recover_missed_flat_on_startup(self, was_monitoring=False):
        """重启对账：服务宕机期间已全平，但账本仍有仓 → 补发收网钉钉"""
        pos = self._get_active_position()
        if pos and self._safe_qty(pos.get("size")) > 0:
            return False

        prev_watched = self._safe_qty(self.watched_qty)
        prev_initial = self._safe_qty(self.initial_qty)
        prev_side = self.current_side

        had_active_book = (
            prev_watched > 0
            or prev_initial > 0
            or prev_side in ("LONG", "SHORT")
            or was_monitoring
        )
        if not had_active_book:
            last_open = self._load_last_journal_entry(self.open_journal)
            if last_open and last_open.get("source") in ("open", "recover"):
                had_active_book = True
                prev_watched = prev_watched or self._safe_qty(last_open.get("qty", 0))
                prev_side = prev_side or last_open.get("side")

        if not had_active_book:
            return False

        logger.warning(
            f"📭 [重启对账] 账本/日志曾有仓 (watched={prev_watched}, side={prev_side}, "
            f"monitoring={was_monitoring}) 但盘口已全平 → 补发收网播报"
        )
        self.client.cancel_all_open_orders(self.symbol)
        self.monitoring = False
        self.watched_qty = 0
        self.initial_qty = 0
        self.base_qty = 0
        self.add_count = 0
        self.current_side = None
        self._save_state()

        verify_note = (
            f"重启对账补发 | 原账本 {prev_watched}张 {prev_side or ''} | "
            f"盘口无持仓 | 挂单已清空 | 智慧大脑复位待命"
        )
        self._call_dingtalk(
            self._dt.report_supervisor_close,
            reason="仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)",
            verify_note=verify_note,
            verified=True,
            swept_dust=False,
        )
        return True

    def _verify_position(self, expected_side=None):
        pos = self._get_active_position()
        if not pos or self._safe_qty(pos.get("size")) <= 0:
            return None
        side = "LONG" if pos["posSide"] == "long" else "SHORT"
        if expected_side and side != expected_side:
            return None
        return pos

    def _is_tp_limit_order(self, o):
        if o.get("ordType") not in ("limit", "post_only", None):
            return False
        val = o.get("reduceOnly")
        if val is True or str(val).lower() in ("true", "1"):
            return True
        if not self.current_side:
            return False
        close_side = "sell" if self.current_side == "LONG" else "buy"
        if str(o.get("side", "")).lower() != close_side:
            return False
        px = float(o.get("px", 0) or 0)
        if px <= 0:
            return False
        return any(tp_price_matches(px, t) for t in self.tv_tps if t > 0)

    def _collect_limit_tp_prices(self):
        prices = []
        for o in self.client.get_pending_orders(self.symbol):
            if not self._is_tp_limit_order(o):
                continue
            px = float(o.get("px", 0) or 0)
            if px > 0:
                prices.append(round(px, 2))
        return sorted(prices)

    def _collect_tp_limit_orders(self):
        orders = []
        for o in self.client.get_pending_orders(self.symbol):
            if not self._is_tp_limit_order(o):
                continue
            px = float(o.get("px", 0) or 0)
            if px <= 0:
                continue
            orders.append({
                "orderId": o.get("ordId"),
                "price": round(px, 2),
                "qty": self._safe_qty(o.get("sz")),
            })
        return dedupe_orders_by_id(orders)

    def _compute_tp_slices(self, qty, exclude_levels=None):
        return compute_tp_slices(
            float(qty),
            self.regime,
            self.tv_tps,
            self.regime_settings,
            exclude_levels=exclude_levels or set(),
            round_qty_fn=lambda x: float(max(self._safe_qty(x), 1)),
        )

    def _sync_consumed_tp_levels(self, live_qty, curr_px):
        anchor = float(self._safe_qty(self.initial_qty or live_qty))
        tol = tp_slice_qty_tolerance(anchor, is_contracts=True)
        open_prices = [float(o.get("price", 0)) for o in self._collect_tp_limit_orders()]
        inferred = infer_filled_tp_levels(
            float(live_qty),
            float(curr_px or 0),
            self.current_side,
            initial_qty=anchor,
            consumed_tp_levels=self.consumed_tp_levels,
            regime=self.regime,
            tv_tps=self.tv_tps,
            regime_settings=self.regime_settings,
            open_tp_prices=open_prices,
            qty_tol=tol,
        )
        merged = sorted({int(x) for x in (self.consumed_tp_levels or [])} | inferred)
        self.consumed_tp_levels = merged
        if hasattr(self, "_save_state"):
            self._save_state()
        return merged

    def _consumed_tp_level_set(self) -> set[int]:
        return {int(x) for x in (self.consumed_tp_levels or []) if int(x) in (1, 2, 3)}

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
                    self.client.cancel_order(self.symbol, ord_id=oid)
                    cancelled += 1
                    time.sleep(0.2)
        if cancelled:
            logger.info(
                f"[User {self.user_id}] 🧹 已撤销已成交档位多余止盈 {cancelled} 张 "
                f"(consumed={sorted(consumed)})"
            )
        return cancelled

    def _classify_qty_change(self, old_qty, new_qty, curr_px=None):
        """与币安 PositionSupervisor 一致：按 initial_qty 识别 TP 吃单 vs 手动减仓。"""
        old_qty = float(self._safe_qty(old_qty))
        new_qty = float(self._safe_qty(new_qty))
        tol = self._qty_match_tol(old_qty, new_qty)
        if new_qty <= 0:
            return "full_close"
        if new_qty > old_qty + tol:
            return "manual_add"
        reduced = old_qty - new_qty
        if reduced <= tol:
            return "unchanged"

        anchor = float(self._safe_qty(self.initial_qty or old_qty))
        if anchor > 0:
            slice_tol = tp_slice_qty_tolerance(anchor, is_contracts=True)
            level = match_qty_reduction_to_tp_level(
                reduced,
                anchor,
                self.regime,
                self.tv_tps,
                self.regime_settings,
                consumed_levels=set(self.consumed_tp_levels),
                qty_tol=slice_tol,
            )
            if level is not None:
                if level not in self.consumed_tp_levels:
                    self.consumed_tp_levels.append(level)
                if curr_px is not None and float(curr_px) > 0:
                    self._sync_consumed_tp_levels(new_qty, float(curr_px))
                return f"tp{level}_filled"

        if curr_px is not None and float(curr_px) > 0:
            self._sync_consumed_tp_levels(new_qty, float(curr_px))
        return "manual_reduce"

    def _reconcile_radar_context(self, recovery: dict | None) -> dict:
        """Gemini 重启：OPEN 日志 + DB 交易 + 最新 TV 三方核实（与币安对齐）。"""
        report: dict = {"sources": [], "warnings": list(recovery.get("checks") or []) if recovery else []}
        if not recovery:
            return report

        trade = recovery_section(recovery, "trade")
        open_log = recovery_section(recovery, "open_log")
        latest_tv = recovery_section(recovery, "latest_tv")

        if trade:
            report["sources"].append("db_trade")
            trade_qty = float(trade.get("quantity") or 0)
            if trade_qty > 0:
                self.initial_qty = max(int(self._safe_qty(self.initial_qty)), int(trade_qty))
            if not any(self.tv_tps) and trade.get("tv_tps"):
                self.tv_tps = [float(x) for x in trade["tv_tps"][:3]]
            if trade.get("regime"):
                self.regime = clamp_regime(trade["regime"])
            if trade.get("side") and not self.last_tv_side:
                self.last_tv_side = trade["side"]

        if open_log:
            report["sources"].append("open_log")
            report["open_log_side"] = open_log.get("side")
            report["open_log_qty"] = open_log.get("qty")
            report["open_log_entry"] = open_log.get("entry")
            open_qty = float(open_log.get("qty") or 0)
            if open_qty > 0:
                self.initial_qty = max(int(self._safe_qty(self.initial_qty)), int(open_qty))
            if open_log.get("tv_tps"):
                self.tv_tps = [float(x) for x in open_log["tv_tps"][:3]]
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
                    self.tv_tps = [float(x) for x in latest_tv["tv_tps"][:3]]
                if latest_tv.get("regime"):
                    self.regime = clamp_regime(latest_tv["regime"])
                if latest_tv.get("atr"):
                    self.current_atr = float(latest_tv["atr"])
            elif tv_action.startswith("CLOSE"):
                report["warnings"].append("tv_close_while_position")

        apply_tv_sl_from_sources(self, latest_tv, open_log, trade)

        report["last_tv_side"] = self.last_tv_side
        report["tv_tps"] = list(self.tv_tps)
        report["regime"] = self.regime
        return report

    def _expected_tp_count(self, tp_pxs=None):
        live_qty = float(self._safe_qty(self.watched_qty))
        if live_qty <= 0:
            tp_pxs = tp_pxs if tp_pxs is not None else self.tv_tps
            return sum(1 for t in tp_pxs if t > 0)
        exclude = set(self.consumed_tp_levels or [])
        return len(self._compute_tp_slices(live_qty, exclude_levels=exclude))

    def _expected_tp_levels(self, live_qty, curr_px=None):
        live_qty = float(self._resolve_live_qty(live_qty))
        exclude = set(self.consumed_tp_levels or [])
        if curr_px and curr_px > 0:
            self._sync_consumed_tp_levels(live_qty, curr_px)
            exclude = set(self.consumed_tp_levels or [])
        slices = self._compute_tp_slices(live_qty, exclude_levels=exclude)
        return [{"level": lvl, "qty": self._safe_qty(q), "price": px} for lvl, q, px in slices]

    def _current_tp_price(self) -> float:
        if hasattr(self.client, "get_current_price"):
            try:
                return float(self.client.get_current_price(self.symbol) or 0)
            except Exception:
                return 0.0
        return 0.0

    def _has_stop_sl_near(self, sl_price: float, tolerance: float = 2.0) -> bool:
        """Alias for StartupReconcileMixin / AdverseRadarMixin (Binance API parity)."""
        return self._has_trigger_sl_near(sl_price, tolerance)

    def _audit_tp_levels(self, live_qty, tolerance=None, curr_px=None):
        """严格审计：每档价位唯一 + 张数符合 regime 比例 + 无孤儿单"""
        live_qty = self._resolve_live_qty(live_qty)
        price_tol = TP_PRICE_MATCH_TOL if tolerance is None else float(tolerance)
        orders = self._collect_tp_limit_orders()
        levels = []
        matched_full = 0
        issues = []

        for lv in self._expected_tp_levels(live_qty, curr_px):
            if lv["qty"] <= 0 or lv["price"] <= 0:
                continue
            at_px = [o for o in orders if tp_price_matches(o["price"], lv["price"], price_tol)]
            status = "ok"
            actual_qty = 0
            if len(at_px) == 0:
                status = "missing"
                issues.append(f"TP{lv['level']} @{lv['price']:.2f} 缺失")
            elif len(at_px) > 1:
                status = "duplicate"
                actual_qty = sum(o["qty"] for o in at_px)
                issues.append(f"TP{lv['level']} @{lv['price']:.2f} 重复 {len(at_px)} 张")
            elif not tp_qty_matches(lv["qty"], at_px[0]["qty"], live_qty, is_contracts=True):
                status = "qty_mismatch"
                actual_qty = at_px[0]["qty"]
                issues.append(
                    f"TP{lv['level']} {actual_qty}张 ≠ 期望 {lv['qty']}张 "
                    f"({self.regime_settings[self.regime]['ratios']})"
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
            issues.append(f"孤儿止盈 @{o['price']:.2f} {o['qty']}张")

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
            "consumed_tp_levels": sorted(self._consumed_tp_level_set()),
        }

    def _format_audit_summary(self, audit):
        parts = []
        consumed = audit.get("consumed_tp_levels") or []
        live_qty = float(audit.get("live_qty") or self._safe_qty(self.watched_qty))
        if consumed:
            pending = [lv for lv in audit.get("levels", []) if lv.get("level") not in consumed]
            rem_qty = sum(int(lv.get("qty") or 0) for lv in pending)
            parts.append(
                f"已成交TP{''.join(str(x) for x in consumed)}"
                f" → 挂剩余{len(pending)}档/{rem_qty}张"
            )
        initial = int(self._safe_qty(self.initial_qty))
        if initial > live_qty > 0:
            parts.append(f"初始{initial}张→现仓{int(live_qty)}张")
        for lv in audit.get("levels", []):
            if lv["price"] <= 0:
                continue
            icon = "✅" if lv["status"] == "ok" else "❌"
            line = f"{icon}TP{lv['level']} {lv['qty']}张@{lv['price']:.2f}"
            if lv["status"] != "ok":
                line += f"({lv['status']})"
            parts.append(line)
        if audit.get("issues"):
            parts.append("问题:" + "; ".join(audit["issues"][:3]))
        return " | ".join(parts) if parts else "无有效 TP"

    def _count_matched_tp_orders(self, tp_pxs, tolerance=None, live_qty=None):
        tol = TP_PRICE_MATCH_TOL if tolerance is None else float(tolerance)
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

    def _has_duplicate_tp_orders(self, tolerance=None):
        tol = TP_PRICE_MATCH_TOL if tolerance is None else float(tolerance)
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

    def _defenses_fully_ok(self, live_qty, dynamic_sl=None, tolerance=None, curr_px=None, *, require_sl=True):
        tol = TP_PRICE_MATCH_TOL if tolerance is None else float(tolerance)
        audit = self._audit_tp_levels(live_qty, tolerance=tol, curr_px=curr_px)
        expected = audit.get("expected", 0)
        if expected == 0:
            if not require_sl:
                return True
            return dynamic_sl is None or self._has_trigger_sl_near(dynamic_sl, tol)
        if audit["matched_full"] < expected:
            return False
        if audit["orphans"]:
            return False
        if require_sl and dynamic_sl and not self._has_trigger_sl_near(dynamic_sl, tol):
            return False
        return True

    def _purge_duplicate_tp_orders(self, live_qty) -> int:
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
                self.client.cancel_order(self.symbol, ord_id=oid)
                cancelled += 1
                time.sleep(0.2)
        if cancelled:
            logger.info(f"🧹 去重撤销多余止盈 {cancelled} 张（保留最优张数）")
        return cancelled

    def _patch_missing_tp_levels(self, live_qty, tolerance=None, curr_px=None):
        price_tol = TP_PRICE_MATCH_TOL if tolerance is None else float(tolerance)
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"
        live_qty = self._resolve_live_qty(live_qty)
        if curr_px is None and hasattr(self.client, "get_current_price"):
            try:
                curr_px = float(self.client.get_current_price(self.symbol) or 0)
            except Exception:
                curr_px = 0.0
        self._sync_consumed_tp_levels(live_qty, float(curr_px or 0))
        self._cancel_tp_orders_for_consumed_levels()
        levels = self._expected_tp_levels(live_qty, curr_px)
        placed = 0

        for lv in levels:
            q, px = int(lv["qty"]), float(lv["price"])
            if q <= 0 or px <= 0:
                continue
            orders = self._collect_tp_limit_orders()
            at_px = [o for o in orders if tp_price_matches(o["price"], px, price_tol)]
            if len(at_px) == 1 and tp_qty_matches(q, at_px[0]["qty"], live_qty, is_contracts=True):
                logger.info(f"  ✓ TP @ {px:.2f} 已存在 {at_px[0]['qty']}张，跳过")
                continue
            if len(at_px) > 1:
                self._purge_duplicate_tp_orders(live_qty)
                orders = self._collect_tp_limit_orders()
                at_px = [o for o in orders if tp_price_matches(o["price"], px, price_tol)]
                if len(at_px) == 1 and tp_qty_matches(q, at_px[0]["qty"], live_qty, is_contracts=True):
                    continue
            for o in at_px:
                if o.get("orderId"):
                    self.client.cancel_order(self.symbol, ord_id=o["orderId"])
                    time.sleep(0.25)
            logger.info(f"  + 补挂 TP{lv['level']} @ {px:.2f} qty={q}张")
            res = self.client.place_limit_order(
                self.symbol, close_side, pos_side, px, q, reduce_only=True,
            )
            if res and self.client._is_success(res):
                placed += 1
            time.sleep(0.4)
        return placed

    def _cancel_orphan_tp_orders(self, live_qty, tolerance=None):
        tol = TP_PRICE_MATCH_TOL if tolerance is None else float(tolerance)
        audit = self._audit_tp_levels(live_qty, tolerance=tol)
        cancelled = 0
        for o in audit["orphans"]:
            if o.get("orderId"):
                self.client.cancel_order(self.symbol, ord_id=o["orderId"])
                cancelled += 1
                time.sleep(0.2)
        if cancelled:
            logger.info(f"🧹 撤销 {cancelled} 张孤儿止盈单")
        return cancelled

    def _cancel_radar_trigger_orders_only(self) -> int:
        """撤销雷达条件单，保留 TV 底线单（Deepcoin 双轨）。"""
        floor_prices = self._shield_tier_prices()
        cancelled = 0
        for t in self.client.get_trigger_orders_pending(self.symbol):
            px = float(t.get("triggerPrice", 0) or 0)
            if floor_prices and any(abs(px - p) <= ADVERSE_STOP_TOLERANCE for p in floor_prices):
                continue
            oid = t.get("ordId")
            if oid:
                self.client.cancel_trigger_order(self.symbol, oid)
                cancelled += 1
                time.sleep(0.2)
        return cancelled

    def _cancel_stop_orders(self):
        cancelled = 0
        for t in self.client.get_trigger_orders_pending(self.symbol):
            oid = t.get("ordId")
            if oid:
                self.client.cancel_trigger_order(self.symbol, oid)
                cancelled += 1
                time.sleep(0.2)
        return cancelled

    def _is_radar_active(self):
        if not self.watched_entry or not self.current_sl:
            return False
        if self.current_side == "LONG":
            return self.current_sl > self.watched_entry
        if self.current_side == "SHORT":
            return self.current_sl < self.watched_entry
        return False

    def _radar_sl_to_pass(self):
        return self.current_sl if self._is_radar_active() else None

    def _audit_requires_nuclear(self, audit):
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
        qty_bad = [lv for lv in audit.get("levels", []) if lv.get("status") == "qty_mismatch"]
        if len(qty_bad) >= 2:
            return True
        missing = sum(1 for lv in audit.get("levels", []) if lv.get("status") == "missing")
        if missing >= 2:
            return True
        if audit.get("orphans") and audit.get("matched_full", 0) == 0:
            return True
        return False

    def _defense_result_from_audit(self, audit, *, skipped=False, rebuilt=False, nuclear=False):
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
            "summary": summary,
        }

    def _reconcile_tp_defenses_on_startup(self, live_qty, entry, dynamic_sl=None):
        logger.info("🔄 重启接管：交易所优先对账止盈（不盲目清场）")
        live_qty = self._resolve_live_qty(live_qty)
        curr_px = 0.0
        if hasattr(self.client, "get_current_price"):
            try:
                curr_px = float(self.client.get_current_price(self.symbol) or 0)
            except Exception:
                curr_px = 0.0
        self._sync_consumed_tp_levels(live_qty, curr_px)
        self._cancel_tp_orders_for_consumed_levels()
        rebuilt = False

        for attempt in range(STARTUP_ORDER_FETCH_RETRIES):
            audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
            if self._defenses_fully_ok(
                live_qty, dynamic_sl=None, curr_px=curr_px, require_sl=False,
            ):
                logger.info(
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
                logger.info(
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
            logger.info(f"✅ 重启增量纠偏完成 | {self._format_audit_summary(audit)}")
            return self._defense_result_from_audit(audit, skipped=not rebuilt, rebuilt=rebuilt)

        logger.warning(
            f"⚠️ 重启对账后仍不齐，升级智能对齐 | {self._format_audit_summary(audit)}"
        )
        return self._smart_realign_defenses(
            live_qty, entry, dynamic_sl=None, reason="重启纠偏升级",
        )

    def _cancel_all_tp_limit_orders(self):
        cancelled = 0
        for o in self.client.get_pending_orders(self.symbol):
            if not self._is_tp_limit_order(o):
                continue
            oid = o.get("ordId")
            if oid:
                self.client.cancel_order(self.symbol, ord_id=oid)
                cancelled += 1
                time.sleep(0.15)
        if cancelled:
            logger.info(f"🧹 已撤销全部限价止盈 {cancelled} 张")
        return cancelled

    def _ensure_radar_sl(self, live_qty, sl_price):
        if not sl_price:
            return False
        sl = float(sl_price)
        if hasattr(self, "_clamp_radar_sl_to_tv_floor"):
            sl = self._clamp_radar_sl_to_tv_floor(sl)
        if self._has_trigger_sl_near(sl):
            return True
        self._cancel_radar_trigger_orders_only()
        time.sleep(0.25)
        self._place_radar_sl(live_qty, sl)
        time.sleep(0.35)
        on_book = self._has_trigger_sl_near(sl)
        if not on_book:
            logger.warning(f"⚠️ 雷达 STOP 已提交但盘口未核实 @ {sl_price:.2f}")
        return on_book

    def _refresh_radar_state_on_recover(self, curr_px, entry):
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
                breakeven_floor = entry + fee_buffer
                trail_sl = max(round(self.best_price - trail_offset, 2), breakeven_floor)
                if not self._is_radar_active() or trail_sl > self.current_sl:
                    self.current_sl = max(self.current_sl or entry, trail_sl)
            else:
                breakeven_floor = entry - fee_buffer
                trail_sl = min(round(self.best_price + trail_offset, 2), breakeven_floor)
                if not self._is_radar_active() or trail_sl < self.current_sl:
                    self.current_sl = min(self.current_sl or entry, trail_sl)
            logger.info(
                f"📡 重启雷达恢复: 进度 {progress:.0%} | best={self.best_price:.2f} | "
                f"SL={self.current_sl:.2f}"
            )
        elif self.current_sl == 0.0:
            self.current_sl = entry

    def _nuclear_realign_tp(self, live_qty, entry, dynamic_sl=None, rounds=3):
        sl_preserve = dynamic_sl is not None
        curr_px = self._current_tp_price()
        last_audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
        for r in range(rounds):
            logger.warning(
                f"☢️ 核武级止盈清场重挂 {r + 1}/{rounds} | 持仓 {live_qty}张 | "
                f"当前 {last_audit['matched_full']}/{last_audit['expected']} | "
                f"{self._format_audit_summary(last_audit)}"
            )
            if sl_preserve:
                self._cancel_all_tp_limit_orders()
            else:
                self.client.cancel_all_open_orders(self.symbol)
            time.sleep(1.0)
            tp_sl = None if sl_preserve else dynamic_sl
            placed = self._rebuild_defenses(live_qty, entry, dynamic_sl=tp_sl)
            logger.info(f"☢️ 核武轮 {r + 1} 新挂 {placed} 笔限价止盈")
            if sl_preserve:
                time.sleep(0.6)
                self._ensure_radar_sl(live_qty, dynamic_sl)
            time.sleep(1.0)
            last_audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
            if self._defenses_fully_ok(live_qty, dynamic_sl, curr_px=curr_px):
                logger.info(f"☢️ 核武重挂成功: {self._format_audit_summary(last_audit)}")
                return last_audit
            logger.warning(
                f"☢️ 核武轮 {r + 1} 仍未对齐: {self._format_audit_summary(last_audit)}"
            )
            time.sleep(1.5)
        return last_audit

    def _full_rebuild_tp_loop(self, live_qty, entry, dynamic_sl=None):
        audit = self._nuclear_realign_tp(live_qty, entry, dynamic_sl=dynamic_sl, rounds=3)
        return audit["matched_full"], audit["pending_prices"], audit["expected"]

    def _ensure_defenses_on_recover(self, live_qty, entry, dynamic_sl=None):
        curr_px = self._current_tp_price()
        audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
        expected = audit["expected"]
        matched = audit["matched_full"]
        pending_prices = audit["pending_prices"]
        logger.info(
            f"📊 防线审计: 持仓 {live_qty}张 | TP {matched}/{expected} | "
            f"{self._format_audit_summary(audit)}"
        )

        if self._has_duplicate_tp_orders():
            self._purge_duplicate_tp_orders(live_qty)
            time.sleep(0.4)
            audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
            matched = audit["matched_full"]
            pending_prices = audit["pending_prices"]

        if self._audit_requires_nuclear(audit):
            logger.warning(
                f"☢️ 审计触发核武级重挂: {len(self._collect_tp_limit_orders())} 张止盈 | "
                f"{self._format_audit_summary(audit)}"
            )
            audit = self._nuclear_realign_tp(live_qty, entry, dynamic_sl=dynamic_sl, rounds=3)
            return audit["matched_full"], audit["pending_prices"], audit["expected"], True

        if self._defenses_fully_ok(live_qty, dynamic_sl, require_sl=False):
            logger.info(
                f"✅ TP123 比例齐全 ({matched}/{expected}) @ {pending_prices}，跳过补挂"
            )
            if dynamic_sl:
                self._ensure_radar_sl(live_qty, dynamic_sl)
            return matched, pending_prices, expected, False

        self._cancel_orphan_tp_orders(live_qty)
        logger.info(f"📋 止盈未齐 ({matched}/{expected})，增量补挂缺失档（保留已有正确单）")
        self._patch_missing_tp_levels(live_qty, curr_px=curr_px)
        time.sleep(0.8)
        audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
        matched = audit["matched_full"]

        if self._defenses_fully_ok(live_qty, dynamic_sl, require_sl=False):
            logger.info(f"✅ 增量补挂成功 ({matched}/{expected}) @ {audit['pending_prices']}")
            if dynamic_sl:
                self._ensure_radar_sl(live_qty, dynamic_sl)
            return matched, audit["pending_prices"], expected, True

        logger.warning(
            f"⚠️ 增量补挂仍不足 ({matched}/{expected}) {audit['issues']}，升级核武级重挂"
        )
        audit = self._nuclear_realign_tp(live_qty, entry, dynamic_sl=dynamic_sl, rounds=3)
        return audit["matched_full"], audit["pending_prices"], expected, True

    def _smart_realign_defenses(self, live_qty, entry, dynamic_sl=None, reason=""):
        if reason:
            logger.info(f"🧠 智能防线对齐: {reason}")
        curr_px = self._current_tp_price()
        self._sync_consumed_tp_levels(live_qty, curr_px)
        self._cancel_tp_orders_for_consumed_levels()
        initial = self._audit_tp_levels(live_qty, curr_px=curr_px)
        if self._defenses_fully_ok(
            live_qty, dynamic_sl=None, curr_px=curr_px, require_sl=False,
        ):
            logger.info(f"✅ 防线已齐，跳过: {self._format_audit_summary(initial)}")
            return {
                "matched": initial["matched_full"],
                "expected": initial["expected"],
                "pending_prices": initial["pending_prices"],
                "rebuilt": False,
                "audit": initial,
                "nuclear": False,
            }

        if self._has_duplicate_tp_orders():
            logger.warning("🧹 检测到重复止盈，去重保留最优单（不清场）")
            self._purge_duplicate_tp_orders(live_qty)
            time.sleep(0.5)
            initial = self._audit_tp_levels(live_qty, curr_px=curr_px)
            if self._defenses_fully_ok(
                live_qty, dynamic_sl=None, curr_px=curr_px, require_sl=False,
            ):
                return self._defense_result_from_audit(initial, skipped=True)

        if self._audit_requires_nuclear(initial):
            logger.warning("🧹 检测到严重错位，清场后重挂")
            self._cancel_all_tp_limit_orders()
            time.sleep(0.5)
            initial = self._audit_tp_levels(live_qty, curr_px=curr_px)

        self._cancel_orphan_tp_orders(live_qty)
        matched, pending_prices, expected, rebuilt = self._ensure_defenses_on_recover(
            live_qty, entry, dynamic_sl=None,
        )
        audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
        nuclear = False

        if expected > 0 and audit["matched_full"] < expected:
            logger.warning(
                f"⚠️ 常规对齐未达标 ({audit['matched_full']}/{expected})，"
                f"升级核武级清场重挂"
            )
            audit = self._nuclear_realign_tp(live_qty, entry, dynamic_sl=dynamic_sl, rounds=3)
            matched = audit["matched_full"]
            pending_prices = audit["pending_prices"]
            rebuilt = nuclear = True

        return {
            "matched": matched,
            "expected": expected,
            "pending_prices": pending_prices,
            "rebuilt": rebuilt,
            "audit": audit,
            "nuclear": nuclear,
        }

    def _place_radar_sl(self, live_qty, sl_price):
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"
        sl_qty = self._resolve_live_qty(live_qty)
        self.client.place_trigger_order(
            self.symbol, close_side, pos_side, sl_qty, sl_price,
            order_type="market", td_mode="cross", mrg_position="merge",
        )

    def _realign_radar_defenses(self, live_qty, entry, new_sl):
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
        return self._ensure_radar_sl(live_qty, sl)

    def _wait_tp_hung(self, tp_pxs, live_qty=None, retries=5, delay=0.8):
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

    def _has_trigger_sl_near(self, sl_price, tolerance=2.0):
        for t in self.client.get_trigger_orders_pending(self.symbol):
            for key in ("triggerPx", "slTriggerPrice", "triggerPrice"):
                val = t.get(key)
                if val is not None and str(val).strip() not in ("", "0"):
                    try:
                        if abs(float(val) - sl_price) <= tolerance:
                            return True
                    except (TypeError, ValueError):
                        pass
        return False

    def _wait_verify(self, checks_fn, retries=3, delay=0.6):
        for i in range(retries):
            result = checks_fn()
            if result:
                return result
            time.sleep(delay)
        return checks_fn()

    def _calculate_tp_quantities(self, total_qty: int, ratios: list) -> tuple:
        """深币最小 1 张限制 + 余数吸收：qty1+qty2+qty3 恒等于 total_qty"""
        if total_qty <= 0:
            return 0, 0, 0

        qty1 = max(1, round(total_qty * ratios[0]))
        remaining = total_qty - qty1
        if remaining <= 0:
            return qty1, 0, 0

        ratio_sum_23 = ratios[1] + ratios[2]
        if ratio_sum_23 <= 0:
            return qty1, 0, remaining

        qty2 = max(0, round(remaining * (ratios[1] / ratio_sum_23)))
        qty3 = remaining - qty2
        if qty3 < 0:
            qty3, qty2 = 0, remaining

        if qty2 == 0 and remaining >= 2:
            qty2, qty3 = 1, remaining - 1
        if qty3 == 0 and remaining >= 2 and qty2 > 1:
            qty3, qty2 = 1, remaining - 1

        assert qty1 + qty2 + qty3 == total_qty, f"TP 分档不守恒: {qty1}+{qty2}+{qty3}!={total_qty}"
        return qty1, qty2, qty3

    def _resolve_live_qty(self, fallback_qty: int) -> int:
        """挂 reduceOnly 前重新读取交易所落账张数，避免冻结/部分成交导致数量漂移"""
        pos = self._get_active_position()
        if pos and self._safe_qty(pos.get("size")) > 0:
            live = self._safe_qty(pos["size"])
            if live != fallback_qty:
                logger.info(f"📐 实盘张数校正: 账本 {fallback_qty} → 交易所 {live}")
            return live
        return fallback_qty

    def handle_signal(self, payload: dict) -> dict:
        raw_action = str(payload.get("action", "")).upper().strip()
        if not raw_action:
            return {"status": "skipped", "reason": "empty_action"}
        self.enqueue_signal(payload)
        return {"status": "ok", "action": raw_action, "detail": {"queued": True}}

    def _safe_float(self, val, default=0.0):
        try:
            if val is None or val == "":
                return default
            return float(val)
        except (TypeError, ValueError):
            return default

    def _safe_int(self, val, default=3):
        try:
            if val is None or val == "":
                return default
            return int(float(val))
        except (TypeError, ValueError):
            return default

    def _process_signal(self, payload):
        from app.services.tv_signal_enrich import merge_supervisor_fallbacks

        payload = merge_supervisor_fallbacks(
            payload,
            regime=self.regime,
            atr=self.current_atr,
        )
        raw_action = str(payload.get("action", "")).strip().upper()
        held_regime = self.regime
        held_atr = self.current_atr
        prev_tv_tps = list(self.tv_tps)
        self.regime = clamp_regime(self._safe_int(payload.get("regime"), 3))

        self.current_atr = self._safe_float(payload.get("atr"), 30.0)
        self.risk_multiplier = float(payload.get("risk_multiplier", 1.0))
        self._apply_tv_entry_context(payload)
        self._apply_tv_sl_from_payload(payload)
        self.tv_price = self._safe_float(payload.get("price"), 0.0)
        self.tv_tps = self._sanitize_tp_prices([
            self._safe_float(payload.get("tv_tp1"), 0),
            self._safe_float(payload.get("tv_tp2"), 0),
            self._safe_float(payload.get("tv_tp3"), 0),
        ])
        close_reason = str(payload.get("reason") or "策略指标反转/波动率安全退出").strip()
        tv_close = extract_tv_close_fields(payload)
        tv_reason = tv_close.get("tv_reason") or close_reason
        tv_side = tv_close.get("tv_side") or str(payload.get("side") or "").strip().upper() or None
        tv_pnl_pct = tv_close.get("tv_pnl_pct")

        def _tv_close_kwargs() -> dict:
            return {
                "close_action": raw_action,
                "tv_close_ctx": tv_close,
                "tv_side": tv_side,
                "tv_pnl_pct": tv_pnl_pct,
                "tv_reason": tv_reason,
            }

        if not raw_action:
            logger.warning("TV 信号缺少 action，已忽略")
            return
        if raw_action in ("LONG", "SHORT", "CLOSE", "CLOSE_PROTECT", "CLOSE_TP3", "UPDATE_SL") or \
                raw_action.startswith("CLOSE"):
            self._record_tv_signal(payload, raw_action)

        if not self._lock.acquire(timeout=120.0):
            logger.error(f"⏱️ 锁等待 120s 超时，信号 {raw_action} 重新入队")
            self._signal_queue.put(payload)
            return

        try:
            self.monitoring = False
            if raw_action == "CLOSE_PROTECT" or raw_action.startswith("CLOSE_PROTECT"):
                pos = self._get_active_position()
                if not pos or self._safe_qty(pos.get("size", 0)) <= 0:
                    logger.info(f"🛡️ 保护性全平到达但盘口已空仓 → 撤单复位 | {tv_reason}")
                    empty_detail: dict = {
                        "close_action": raw_action,
                        "tv_side": tv_side,
                        "reason": tv_reason,
                        "tv_reason": tv_reason,
                        "action": "cancel_orders_reset",
                        "exchange": self.exchange_id,
                    }
                    empty_detail.update({k: v for k, v in tv_close.items() if v is not None})
                    if tv_pnl_pct is not None:
                        empty_detail["tv_pnl_pct"] = round(float(tv_pnl_pct), 2)
                    self.client.cancel_all_open_orders(self.symbol)
                    self.monitoring = False
                    self._save_state()
                    self._log("CLOSE_PROTECT_EMPTY", f"🛡️ 空仓保护性全平：撤单复位 | {tv_reason}", empty_detail)
                    self._alert(
                        "info",
                        "CLOSE_PROTECT_EMPTY",
                        "空仓保护 · 撤单复位",
                        f"Deepcoin 实盘无持仓，已撤单并复位 | {tv_reason}",
                        empty_detail,
                    )
                else:
                    self._close_all(f"🛡️ 保护性全平：{tv_reason}", **_tv_close_kwargs())
            elif raw_action == "CLOSE_TP3":
                self._close_all(
                    f"🎯 TP3完美收网：{tv_reason or '大趋势吃满'}",
                    **_tv_close_kwargs(),
                )
            elif raw_action == "CLOSE_STOPLOSS":
                self._close_all(f"🛑 {tv_reason or '触碰硬止损或追踪保本线'}", **_tv_close_kwargs())
            elif raw_action == "CLOSE":
                self._close_all(f"🧹 换防清场：{tv_reason}", **_tv_close_kwargs())
            elif raw_action == "UPDATE_SL":
                self._handle_update_sl(payload)
            elif raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self._save_state()
                self._handle_smart_entry(
                    raw_action,
                    held_regime=held_regime,
                    held_atr=held_atr,
                    prev_tv_tps=prev_tv_tps,
                )
            else:
                logger.warning(f"未识别的 TV action: {raw_action}")
        finally:
            self._lock.release()

    def _handle_manual_flat_detected(self, reason):
        """人工全平 / 止盈吃满：智能复位账本"""
        logger.info(f"📭 感知空仓: {reason}")
        self.monitoring = False
        self.watched_qty = 0
        self.initial_qty = 0
        self.base_qty = 0
        self.add_count = 0
        self.current_side = None
        self.client.cancel_all_open_orders(self.symbol)
        self._save_state()
        self._report_flat_close(reason or "仓位归零 (人工全平 / 止盈吃满)")

    def _apply_tv_entry_context(self, payload: dict) -> None:
        fields = parse_tv_entry_fields(payload)
        self._tv_entry_fields = fields
        self._entry_type = fields["entry_type"]
        self._explicit_entry_type = "entry_type" in (payload or {})
        if fields.get("regime") is not None:
            self._tv_entry_fields["regime"] = fields["regime"]
        elif getattr(self, "regime", None):
            self._tv_entry_fields["regime"] = self.regime

    def _uses_tv_entry_routing(self) -> bool:
        return True

    def _resolve_entry_leverage(self) -> int:
        return int(self.leverage)

    def _resolve_entry_qty(self, curr_px: float) -> tuple[int, dict]:
        equity = read_contract_equity(self.client)
        leverage = self._resolve_entry_leverage()
        tv_fields = getattr(self, "_tv_entry_fields", None) or {}
        entry_type = getattr(self, "_entry_type", "OPEN")
        return resolve_vps_entry_qty_deepcoin(
            live_balance=equity,
            initial_principal=self.initial_principal,
            entry_type=entry_type,
            base_qty=float(getattr(self, "base_qty", 0) or 0),
            price=float(curr_px or self.tv_price or 0),
            tv_sl=float(getattr(self, "tv_sl", 0) or 0),
            regime=int(tv_fields.get("regime") or self.regime),
            exchange_leverage=leverage,
            face_value=self.face_value,
        )

    def _max_add_times(self) -> int:
        return max(int(getattr(settings, "MAX_ADD_TIMES", 2) or 2), 0)

    def _can_add_more(self) -> tuple[bool, str]:
        cap = self._max_add_times()
        count = int(getattr(self, "add_count", 0) or 0)
        if cap <= 0:
            return False, "加仓已禁用"
        if count >= cap:
            return False, f"已达最大加仓次数 {count}/{cap}"
        if float(getattr(self, "base_qty", 0) or 0) <= 0:
            return False, "缺少首仓基准数量 base_qty"
        return True, ""

    def _force_flat_before_open(self, reason: str) -> bool:
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        self._close_all(reason)
        if not self._wait_until_flat():
            logger.error("先平后开：平仓后仍未归零，暂缓新开仓")
            return False
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.4)
        return True

    def _handle_tv_entry(self, action, curr_px, *, has_pos, current_side):
        entry_type = getattr(self, "_entry_type", "OPEN")
        if entry_type in ENTRY_TYPES_ADD:
            if not has_pos:
                logger.info(f"⚠️ {entry_type} 无持仓，降级为 OPEN")
                self._open_position(action, curr_px)
                return
            if current_side != action:
                logger.info(f"⚠️ {entry_type} 方向不一致，先平后开")
                if not self._force_flat_before_open(f"{entry_type} 反向后降级 OPEN"):
                    return
                self._open_position(action, curr_px)
                return
            ok, skip_reason = self._can_add_more()
            if not ok:
                logger.info(f"⏭️ {entry_type} 跳过: {skip_reason}")
                self._alert(
                    "info", entry_type,
                    "加仓跳过",
                    f"用户 {self.user_id} {entry_type}: {skip_reason}",
                    {"add_count": self.add_count, "max_add_times": self._max_add_times()},
                )
                return
            self._add_to_position(action, curr_px, entry_type)
            return

        if has_pos:
            logger.info(f"⚡ TV OPEN [{action}] 先平后开")
            if not self._force_flat_before_open("TV OPEN 先平后开"):
                return
        self._open_position(action, curr_px)

    def _add_to_position(self, action, curr_px, entry_type):
        pos_before = self._get_active_position()
        prev_qty = self._safe_qty(pos_before.get("size", 0)) if pos_before else 0
        leverage = self._resolve_entry_leverage()
        self.client.set_leverage(self.symbol, leverage=leverage)

        qty, sizing_meta = self._resolve_entry_qty(curr_px)
        if qty <= 0:
            logger.error(f"{entry_type} 余额不足，无法加仓")
            self._alert("warning", "INSUFFICIENT_BALANCE", "余额不足", f"用户 {self.user_id} {entry_type} 无法加仓")
            return

        open_side = "buy" if action == "LONG" else "sell"
        pos_side = "long" if action == "LONG" else "short"
        logger.info(
            f"📈 [{entry_type}] 同向追加: {open_side} +{qty} 张 | "
            f"base={sizing_meta.get('base_qty')} × {sizing_meta.get('add_qty_ratio')}",
        )
        self.client.place_market_order(self.symbol, open_side, pos_side, qty)
        time.sleep(2.0)

        pos = self._get_active_position()
        if not pos or self._safe_qty(pos.get("size", 0)) <= 0:
            logger.error(f"{entry_type} 加仓后未检测到持仓")
            return

        real_qty = self._safe_qty(pos["size"])
        entry_price = float(pos.get("entry_price") or self.watched_entry or 0)
        add_qty = max(real_qty - prev_qty, qty)
        self.current_side = action
        self.watched_qty = real_qty
        self.watched_entry = entry_price
        self.initial_qty = float(self.initial_qty or prev_qty) + add_qty
        self.add_count = int(getattr(self, "add_count", 0) or 0) + 1
        self.monitoring = True

        shield = {}
        tp_heal = {}
        if float(getattr(self, "tv_sl", 0) or 0) > 0:
            shield = self._sync_tv_hard_stop(real_qty, force_replace=True)
        if self.tv_tps and any(float(t or 0) > 0 for t in self.tv_tps):
            dynamic_sl = self._radar_sl_to_pass()
            tp_heal = self._smart_realign_defenses(
                real_qty, entry_price, dynamic_sl=dynamic_sl,
                reason=f"{entry_type} 加仓后止盈数量对齐",
            )
        self._save_state()

        theme = resolve_exchange_theme(self.exchange_id)
        detail = {
            "exchange": self.exchange_id,
            "entry_type": entry_type,
            "side": action,
            "add_qty": add_qty,
            "total_qty": real_qty,
            "entry": entry_price,
            "tv_price": self.tv_price,
            "tv_tps": list(self.tv_tps),
            "leverage": leverage,
            "atr": self.current_atr,
            "add_count": self.add_count,
            "max_add_times": self._max_add_times(),
            **sizing_meta,
        }
        if shield:
            detail["shield"] = shield
            detail["tv_sl"] = self.tv_sl
        if tp_heal:
            detail["tp_realign"] = tp_heal
        verify_note = ""
        if tp_heal.get("expected"):
            verify_note += f" | 止盈 {tp_heal.get('matched', 0)}/{tp_heal.get('expected')} 档已对齐"
        if shield.get("aligned") or shield.get("skipped") == "live_already_aligned":
            sl_label = shield.get("label") or self._hard_stop_label()
            verify_note = f" | {sl_label}已核实 @{shield.get('stop_price', 0):.2f}"
        add_label = "金字塔加仓" if entry_type == "PYRAMID" else "浮盈加仓"
        self._log(
            "OPEN",
            f"📈 {add_label}：{action} +{add_qty} → 总 {real_qty} 张 @ {entry_price}{verify_note}",
            detail,
        )
        self._alert(
            "info",
            entry_type,
            f"{theme['accent']} {add_label} · {theme['label']}",
            f"{action} +{add_qty} 张 → 总 {real_qty} @ {entry_price} | "
            f"首仓 {sizing_meta.get('base_qty')} × {sizing_meta.get('add_qty_ratio')} "
            f"= +{add_qty} ({self.add_count}/{self._max_add_times()}){verify_note}",
            detail,
        )

    def _handle_smart_entry(
        self,
        action,
        *,
        held_regime: int | None = None,
        held_atr: float | None = None,
        prev_tv_tps: list | None = None,
    ):
        threshold = float(settings.SAME_DIR_IGNORE_PRICE_DIFF_PCT)
        held_regime = held_regime if held_regime is not None else self.regime
        held_atr = float(held_atr if held_atr is not None else self.current_atr)

        pos = self._get_active_position()
        has_pos = bool(pos and self._safe_qty(pos.get("size", 0)) > 0)
        current_side = None
        entry_price = float(self.watched_entry or 0)
        if has_pos:
            current_side = "LONG" if pos.get("posSide") == "long" else "SHORT"
            entry_price = float(pos.get("entry_price") or entry_price or 0)

        curr_px = self.client.get_current_price(self.symbol)
        if curr_px <= 0:
            logger.error("无法获取当前价格，跳过建仓信号")
            return

        self._handle_tv_entry(action, curr_px, has_pos=has_pos, current_side=current_side)

    def _close_then_open_entry(self, action, curr_px, ev):
        threshold = float(settings.SAME_DIR_IGNORE_PRICE_DIFF_PCT)
        reason = format_reopen_reason(ev, threshold)
        logger.info(f"⚡ 收到建仓信号 [{action}]，{reason}")
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
            logger.error("同向换仓平仓后仍未归零，暂缓新开仓")
            return
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.4)
        self._open_position(action, curr_px)

    def _refresh_same_direction_tps(self, action, entry_price, ev, *, prev_tv_tps: list):
        pos = self._get_active_position()
        if not pos:
            logger.warning("同向止盈更新时无持仓")
            return

        real_qty = self._safe_qty(pos.get("size", 0))
        self.current_side = action
        self.watched_qty = real_qty
        self.watched_entry = entry_price
        self.monitoring = True

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
        msg = f"{format_refresh_reason(ev, threshold)} {prev_tv_tps} → {self.tv_tps}"
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
        self._rebuild_defenses(real_qty, entry_price, dynamic_sl=dynamic_sl)
        if float(getattr(self, "tv_sl", 0) or 0) > 0:
            shield = self._sync_tv_hard_stop(real_qty, force_replace=True)
            detail["tv_sl"] = self.tv_sl
            detail["shield"] = shield
        self._save_state()

    def _open_position(self, action, curr_px):
        leverage = self._resolve_entry_leverage()
        self.client.set_leverage(self.symbol, leverage=leverage)
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.4)
        qty, sizing_meta = self._resolve_entry_qty(curr_px)
        if qty <= 0:
            err = sizing_meta.get("error", "insufficient_balance")
            logger.error(f"开仓失败: {err} | {sizing_meta}")
            self._alert("warning", "INSUFFICIENT_BALANCE", "开仓失败", f"用户 {self.user_id}: {err}", sizing_meta)
            return
        open_side = "buy" if action == "LONG" else "sell"
        pos_side = "long" if action == "LONG" else "short"
        entry_type = getattr(self, "_entry_type", "OPEN")

        logger.info(
            f"🚀 [VPS开仓] {open_side} {qty} 张 | {entry_type} R{self.regime} | "
            f"名义{sizing_meta.get('order_amount')}U / sl_dist={sizing_meta.get('sl_distance')}"
        )
        self.client.place_market_order(self.symbol, open_side, pos_side, qty)
        time.sleep(2.0)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self.current_side = action
            real_qty = self._safe_qty(pos['size'])
            entry_price = float(pos.get('entry_price', 0) or 0)
            cap_px = self.client.get_current_price(self.symbol) or curr_px
            cap_result = self._enforce_regime_cap_alignment(
                real_qty, entry_price, cap_px, reason="开仓后叠仓核验",
            )
            if cap_result.get("new_qty"):
                real_qty = self._safe_qty(cap_result["new_qty"])
            self.base_qty = real_qty
            self.initial_qty = real_qty
            self.add_count = 0
            self._protect_and_monitor(real_qty, entry_price or pos['entry_price'])

    def _protect_and_monitor(self, qty, entry_price):
        self._reset_adverse_radar()
        tp_pxs = self.tv_tps
        self.current_sl = entry_price
        self.best_price = entry_price
        self.watched_qty, self.watched_entry, self.monitoring = qty, entry_price, True
        self._save_state()

        self._ensure_price_ws()

        verified = self._wait_verify(lambda: self._verify_position(self.current_side))
        if verified:
            result = self._smart_realign_defenses(
                self._safe_qty(verified["size"]), verified["entry_price"],
                reason="开仓后智能防线对齐",
            )
            matched, expected = result["matched"], result["expected"]
            audit = result["audit"]
            verify_note = (
                f"持仓 {verified['size']}张 @ {verified['entry_price']:.2f} | "
                f"限价止盈 {matched}/{expected} 档 | {self._format_audit_summary(audit)}"
            )
            self._record_open_log(
                self.current_side, self._safe_qty(verified["size"]), verified["entry_price"], source="open",
            )
            self._dt.report_supervisor_open(
                self.current_side, verified['entry_price'], self.tv_price,
                verified['size'], tp_pxs, self.current_atr, self.regime, self.tv_tps,
                verify_note=verify_note,
                tp_audit=audit,
            )
            if expected > 0 and matched < expected:
                self._dt.report_system_alert(
                    "开仓后限价止盈未全部挂上",
                    f"{self.current_side} {verified['size']}张 | 仅 {matched}/{expected} 档 | "
                    f"{self._format_audit_summary(audit)}",
                )
            shield = self._sync_tv_hard_stop(self._safe_qty(verified["size"]), at_open=True)
            if shield.get("placed", 0) > 0:
                label = shield.get("label") or self._hard_stop_label()
                logger.info(
                    f"🛡️ 开仓 {label}已挂 @{shield.get('stop_price', 0):.2f} | "
                    f"{verified['size']}张"
                )
        else:
            logger.warning("开仓钉钉跳过：实盘持仓核查未通过")
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _ensure_price_ws(self):
        self.client.start_public_price_ws(self.symbol)

    def _radar_activation_progress(self, curr_px):
        if curr_px <= 0 or not self.watched_entry:
            return 0.0
        tp1_dist = abs(self.tv_tps[0] - self.watched_entry) if self.tv_tps[0] > 0 else self.current_atr * 1.5
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

    def _sentinel_poll_sec(self, curr_px=0.0):
        if self._is_radar_active():
            return SENTINEL_POLL_RADAR
        if curr_px > 0 and self._radar_activation_progress(curr_px) >= 0.5:
            return SENTINEL_POLL_ARMING
        return SENTINEL_POLL_NORMAL

    def _process_radar_trailing(self, real_amt, curr_px):
        tp1_dist = abs(self.tv_tps[0] - self.watched_entry) if self.tv_tps[0] > 0 else self.current_atr * 1.5
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

        if self.current_side == "LONG":
            breakeven_floor = self._clamp_radar_sl_to_tv_floor(self.watched_entry + fee_buffer)
            new_sl = max(round(self.best_price - trail_offset, 2), breakeven_floor)
            on_book = self._has_trigger_sl_near(new_sl)
            if self._radar_activation_reached(curr_px) and not on_book:
                self.current_sl = new_sl
                self._save_state()
                placed = self._realign_radar_defenses(real_amt, self.watched_entry, new_sl)
                if not placed:
                    placed = bool(self._ensure_radar_sl(real_amt, new_sl))
                if placed or self._has_trigger_sl_near(new_sl):
                    self._dt.report_intervention(
                        real_amt, self.watched_entry, new_sl,
                        f"🚀 档位{self.regime} 雷达补挂保本盾 @ {new_sl:.2f}",
                        verify_note=f"条件止损 @ {new_sl:.2f} | 持仓 {real_amt}张",
                    )
                    return True
                logger.warning(f"雷达补挂失败：条件止损 @{new_sl} 实盘核查未通过")
                return False
            should_trail = new_sl > self.current_sl + 1.0
            should_arm = self._radar_activation_reached(curr_px) and not on_book
            if should_trail or should_arm:
                self.current_sl = new_sl
                self._save_state()
                placed = self._realign_radar_defenses(real_amt, self.watched_entry, new_sl)
                if not placed and not on_book:
                    placed = bool(self._ensure_radar_sl(real_amt, new_sl))
                if placed or self._has_trigger_sl_near(new_sl):
                    self._dt.report_intervention(
                        real_amt, self.watched_entry, new_sl,
                        f"🚀 档位{self.regime} 雷达实时跟踪：保本盾推升至 {new_sl:.2f}",
                        verify_note=f"条件止损 @ {new_sl:.2f} | 持仓 {real_amt}张 | 轮询 {SENTINEL_POLL_RADAR}s",
                    )
                    return True
                logger.warning(f"雷达钉钉跳过：条件止损 @{new_sl} 实盘核查未通过")
        else:
            breakeven_floor = self._clamp_radar_sl_to_tv_floor(self.watched_entry - fee_buffer)
            new_sl = min(round(self.best_price + trail_offset, 2), breakeven_floor)
            on_book = self._has_trigger_sl_near(new_sl)
            if self._radar_activation_reached(curr_px) and not on_book:
                self.current_sl = new_sl
                self._save_state()
                placed = self._realign_radar_defenses(real_amt, self.watched_entry, new_sl)
                if not placed:
                    placed = bool(self._ensure_radar_sl(real_amt, new_sl))
                if placed or self._has_trigger_sl_near(new_sl):
                    self._dt.report_intervention(
                        real_amt, self.watched_entry, new_sl,
                        f"🚀 档位{self.regime} 雷达补挂保本顶线 @ {new_sl:.2f}",
                        verify_note=f"条件止损 @ {new_sl:.2f} | 持仓 {real_amt}张",
                    )
                    return True
                logger.warning(f"雷达补挂失败：条件止损 @{new_sl} 实盘核查未通过")
                return False
            should_trail = (
                self.current_sl <= 0
                or self.current_sl >= self.watched_entry
                or new_sl < self.current_sl - 1.0
            )
            should_arm = self._radar_activation_reached(curr_px) and not on_book
            if should_trail or should_arm:
                self.current_sl = new_sl
                self._save_state()
                placed = self._realign_radar_defenses(real_amt, self.watched_entry, new_sl)
                if not placed and not on_book:
                    placed = bool(self._ensure_radar_sl(real_amt, new_sl))
                if placed or self._has_trigger_sl_near(new_sl):
                    self._dt.report_intervention(
                        real_amt, self.watched_entry, new_sl,
                        f"🚀 档位{self.regime} 雷达实时跟踪：保本顶线下压至 {new_sl:.2f}",
                        verify_note=f"条件止损 @ {new_sl:.2f} | 持仓 {real_amt}张 | 轮询 {SENTINEL_POLL_RADAR}s",
                    )
                    return True
                logger.warning(f"雷达钉钉跳过：条件止损 @{new_sl} 实盘核查未通过")
        return False

    def _sentinel_loop(self):
        """哨兵：持仓/TP 防线 + 雷达移动保本（自适应轮询 2~6 秒）"""
        last_px = 0.0
        while self.monitoring:
            try:
                if not self._lock.acquire(timeout=2.0):
                    continue
                try:
                    pos = self._get_active_position()
                    real_amt = self._safe_qty(pos.get("size")) if pos else 0
                    actual_side = "LONG" if pos and pos.get('posSide') == "long" else "SHORT"

                    if real_amt == 0:
                        if self.watched_qty > 0:
                            self._handle_manual_flat_detected(
                                "仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)"
                            )
                        break

                    if self.watched_qty > 0 and self._should_finalize_tp_victory(real_amt):
                        self._sweep_dust_and_finalize(
                            "仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)"
                        )
                        break

                    if self.last_tv_side and actual_side != self.last_tv_side:
                        prev = self.last_tv_side
                        self.last_tv_side = actual_side
                        logger.info(
                            f"方向校正: 实盘 {actual_side} 覆盖 stale TV {prev}（不强制全平）"
                        )
                        self._save_state()
                    elif not self.last_tv_side:
                        self.last_tv_side = actual_side
                        self._save_state()

                    entry_px = float(pos.get("entry_price", 0) or self.watched_entry or 0) if pos else 0.0
                    cap_px = self.client.get_current_price(self.symbol) or entry_px
                    cap_result = self._enforce_regime_cap_alignment(
                        real_amt, entry_px, cap_px or entry_px, reason="哨兵巡检",
                    )
                    if cap_result.get("trimmed", 0) > 0 and cap_result.get("new_qty"):
                        real_amt = self._safe_qty(cap_result["new_qty"])
                        self.watched_qty = real_amt

                    qty_changed = qty_change_significant(
                        self.watched_qty,
                        real_amt,
                        is_contracts=True,
                    )
                    if qty_changed:
                        old_qty = self.watched_qty
                        curr_px_chg = self.client.get_current_price(self.symbol) or float(
                            pos.get("entry_price", 0) or 0
                        )
                        orch = self._orchestrate_qty_change(
                            float(old_qty),
                            float(real_amt),
                            float(pos.get("entry_price", 0) or self.watched_entry or 0),
                            float(curr_px_chg),
                        )
                        self.watched_qty = real_amt
                        self.watched_entry = pos["entry_price"]
                        change_type = orch.get("change_type", "manual_reduce")
                        result = orch.get("defense") or {}
                        action_msg = orch.get("action_msg", change_type)
                        logger.info(
                            f"🔄 [智慧大脑] 仓位变化 [{change_type}] {old_qty} ➔ {real_amt}，智能重对齐"
                        )
                        self._save_state()
                        verified = self._verify_position(self.current_side)
                        if verified and self._safe_qty(verified['size']) == real_amt:
                            audit_summary = self._format_audit_summary(result.get("audit") or {})
                            verify_note = (
                                f"核实 {real_amt}张 @ {verified['entry_price']:.2f} | "
                                f"初始{int(self._safe_qty(self.initial_qty))} | "
                                f"止盈 {result.get('matched', 0)}/{result.get('expected', 0)} 档 | "
                                f"{audit_summary}"
                            )
                            if change_type.startswith("tp"):
                                self._alert(
                                    "info", "TP_FILL",
                                    f"部分止盈吃单 · {change_type.upper()}",
                                    verify_note,
                                    orch,
                                )
                            else:
                                self._dt.report_manual_position_change(
                                    action_msg, old_qty, real_amt, verified['entry_price'],
                                    verify_note=verify_note,
                                    tp_audit=result.get("audit"),
                                )
                            if result["expected"] > 0 and result["matched"] < result["expected"]:
                                self._dt.report_system_alert(
                                    "人工异动后止盈未对齐",
                                    f"{self._format_audit_summary(result['audit'])}",
                                )
                        else:
                            logger.warning("人工异动钉钉跳过：实盘核查未通过")

                    self._scan_ticks += 1
                    if not qty_changed and self._scan_ticks % 10 == 0:
                        audit = self._audit_tp_levels(real_amt)
                        if audit["issues"]:
                            logger.info(
                                f"🔍 定期扫描发现异常: {audit['issues']}，触发智能补挂"
                            )
                            sl_to_pass = self._radar_sl_to_pass()
                            self._smart_realign_defenses(
                                real_amt, self.watched_entry, dynamic_sl=sl_to_pass,
                                reason="定期防线扫描",
                            )

                    curr_px = self.client.get_current_price(self.symbol)
                    if curr_px <= 0:
                        curr_px = last_px
                    else:
                        last_px = curr_px
                    if curr_px <= 0:
                        continue
                    if self.current_side == "LONG":
                        self.best_price = max(self.best_price, curr_px)
                    else:
                        self.best_price = min(self.best_price, curr_px)

                    progress = self._radar_activation_progress(curr_px)
                    self._orchestrate_defense_monitoring(real_amt, curr_px)
                    if (
                        not self.adverse_sl_armed
                        and not self.adverse_consumed_tiers
                        and progress >= 0.5
                        and not self._is_radar_active()
                        and self._scan_ticks % 5 == 0
                    ):
                        logger.info(
                            f"📡 雷达预热: 进度 {progress:.0%} | 现价 {curr_px:.2f} | "
                            f"轮询 {SENTINEL_POLL_ARMING}s"
                        )
                finally:
                    self._lock.release()
            except Exception as e:
                logger.error(f"哨兵异常: {e}")
            if self.monitoring:
                time.sleep(self._sentinel_poll_sec(last_px))

    def _rebuild_defenses(self, qty, entry, dynamic_sl=None):
        """仅挂剩余 TP 档（已成交档位跳过），与币安 _rebuild_tp_limit_orders 对齐。"""
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"

        live_qty = self._resolve_live_qty(qty)
        if live_qty <= 0:
            logger.warning(f"重建防线跳过：交易所无可用持仓 (传入 {qty} 张)")
            return 0
        if live_qty != qty:
            self.watched_qty = live_qty
            self._save_state()

        curr_px = 0.0
        if hasattr(self.client, "get_current_price"):
            try:
                curr_px = float(self.client.get_current_price(self.symbol) or 0)
            except Exception:
                curr_px = 0.0
        self._sync_consumed_tp_levels(live_qty, curr_px)
        self._cancel_tp_orders_for_consumed_levels()
        levels = self._expected_tp_levels(live_qty, curr_px)
        placed = 0
        consumed = sorted(self._consumed_tp_level_set())
        level_desc = " ".join(
            f"TP{lv['level']}={lv['qty']}@{lv['price']:.2f}" for lv in levels if lv["qty"] > 0
        )
        logger.info(
            f"🕸️ 补挂剩余止盈: 持仓 {live_qty} 张"
            + (f" | 已成交TP{''.join(str(x) for x in consumed)}" if consumed else "")
            + f" → {level_desc or '无剩余档'}"
        )

        for lv in levels:
            q, px = int(lv["qty"]), float(lv["price"])
            if q > 0 and px > 0:
                res = self.client.place_limit_order(
                    self.symbol, close_side, pos_side, px, q, reduce_only=True,
                )
                if res and self.client._is_success(res):
                    placed += 1
                time.sleep(0.35)

        if dynamic_sl:
            sl_qty = self._resolve_live_qty(live_qty)
            self.client.place_trigger_order(
                self.symbol, close_side, pos_side, sl_qty, dynamic_sl,
                order_type="market", td_mode="cross", mrg_position="merge",
            )
        return placed

    def _close_all(
        self,
        reason="",
        force_align=None,
        *,
        close_action: str | None = None,
        tv_close_ctx: dict | None = None,
        tv_side: str | None = None,
        tv_pnl_pct: float | None = None,
        tv_reason: str | None = None,
    ):
        """三重把关之二：TV 全平/保护性全平 → 先撤单释放冻结仓位，6 轮阶梯强平至归零"""
        entry_snapshot = float(self.watched_entry or 0)
        qty_snapshot = float(self.watched_qty or 0)
        side_snapshot = self.current_side
        trade_id_snapshot = self.current_trade_id
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        closed_successfully = False

        for round_i in range(6):
            pos = self._get_active_position()
            if not pos or self._safe_qty(pos.get("size")) == 0:
                closed_successfully = True
                break

            close_side = "sell" if pos["posSide"] == "long" else "buy"
            live_sz = self._safe_qty(pos["size"])
            logger.info(f"🔪 强平第 {round_i + 1}/6 轮: {close_side} {live_sz}张 reduceOnly")
            self.client.place_market_order(
                self.symbol, close_side, pos["posSide"], live_sz, reduce_only=True,
            )
            time.sleep(1.5)

        if not closed_successfully:
            residual = self._get_active_position()
            residual_sz = self._safe_qty(residual["size"]) if residual else 0
            if residual_sz > 0 and self._is_dust_qty(residual_sz):
                close_side = "sell" if residual["posSide"] == "long" else "buy"
                logger.warning(f"🐜 强平后残 {residual_sz}张，触发蚂蚁仓扫尾")
                self.client.place_market_order(
                    self.symbol, close_side, residual["posSide"], residual_sz, reduce_only=True,
                )
                time.sleep(1.0)
                closed_successfully = self._verify_flat()
            if not closed_successfully:
                residual = self._get_active_position()
                residual_sz = self._safe_qty(residual["size"]) if residual else 0
                logger.error(f"❌ 6 轮强平后仍有残单: {residual_sz}张")
                self._dt.report_system_alert(
                    "强平未完全归零",
                    f"6 轮市价平仓后仍剩 {residual_sz} 张，请人工核查 Deepcoin 盘口",
                )

        self.monitoring = False
        self._disarm_adverse_staged_stops()
        self._reset_adverse_radar(keep_tv_sl=False)
        self.watched_qty = 0
        self.initial_qty = 0
        self.base_qty = 0
        self.add_count = 0
        self.current_side = None
        self._save_state()
        self.client.cancel_all_open_orders(self.symbol)

        if reason and closed_successfully:
            if force_align:
                real_side, expected_side = force_align
                flat = self._wait_verify(self._verify_flat, retries=6, delay=0.5)
                verify_note = "盘口无持仓 | 挂单已清空 | 智慧大脑复位待命"
                if not flat:
                    verify_note += " | REST 同步略延迟"
                self._dt.report_force_align(real_side, expected_side, verify_note=verify_note)
            else:
                self._report_flat_close(
                    reason,
                    close_action=close_action,
                    tv_close_ctx=tv_close_ctx,
                    tv_side=tv_side,
                    tv_pnl_pct=tv_pnl_pct,
                    tv_reason=tv_reason,
                    entry_snapshot=entry_snapshot,
                    qty_snapshot=qty_snapshot,
                    side_snapshot=side_snapshot,
                    trade_id_snapshot=trade_id_snapshot,
                )

    def recover_state_on_startup(self):
        """重启闪电接管：对账 TV/开仓日志 → 核实实盘 → 智能补挂 TP123 → 恢复雷达"""
        try:
            saved_monitoring = False
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    s = json.load(f)
                    saved_monitoring = bool(s.get("monitoring"))
                    self.last_tv_side = s.get("last_tv_side")
                    self.current_side = s.get("current_side")
                    self.current_sl = s.get("current_sl", 0.0)
                    self.regime = clamp_regime(s.get("regime", 3))
                    self.current_atr = s.get("current_atr", 30.0)
                    self.tv_tps = self._sanitize_tp_prices(s.get("tv_tps", [0.0, 0.0, 0.0]))
                    self.tv_price = float(s.get("tv_price", 0.0) or 0.0)
                    self.best_price = s.get("best_price", 0.0)
                    self.watched_qty = s.get("watched_qty", 0)
                    self.watched_entry = s.get("watched_entry", 0.0)
                    self.initial_qty = s.get("initial_qty", 0)
                    self.base_qty = float(s.get("base_qty", 0) or s.get("initial_qty", 0) or 0)
                    self.add_count = int(s.get("add_count", 0) or 0)
                    self.consumed_tp_levels = [
                        int(x) for x in (s.get("consumed_tp_levels") or []) if int(x) in (1, 2, 3)
                    ]
                    self.last_tv_signal = s.get("last_tv_signal")
                    self.adverse_sl_armed = bool(s.get("adverse_sl_armed", False))
                    self.adverse_sl_prices = [
                        float(x) for x in (s.get("adverse_sl_prices") or [])
                    ]
                    self.adverse_consumed_tiers = [
                        float(x) for x in (s.get("adverse_consumed_tiers") or [])
                    ]
                    self._adverse_last_repair_ts = float(s.get("adverse_last_repair_ts", 0) or 0)
                    self.adverse_arm_dingtalk_sent = bool(s.get("adverse_arm_dingtalk_sent", False))
                    self.tv_sl = float(s.get("tv_sl", 0) or 0)

            if self._scan_and_sweep_dust_on_startup():
                return

            if self._recover_missed_flat_on_startup(was_monitoring=saved_monitoring):
                return

            pos = self._get_active_position()
            if pos and self._safe_qty(pos.get("size", 0)) != 0:
                reconcile = self._reconcile_context_on_recover(pos)
                reconcile_notes = reconcile["notes"]
                real_amt = self._safe_qty(pos["size"])
                side = "LONG" if pos.get("posSide") == "long" else "SHORT"
                self.current_side = side

                if reconcile.get("tv_close"):
                    logger.warning("🔄 [重启] TV 最新为平仓指令，执行清场")
                    self._close_all(
                        f"🔄 重启对账: TV已发{(self.last_tv_signal or {}).get('action', 'CLOSE')}，执行清场"
                    )
                    return

                if reconcile.get("direction_mismatch") or side != self.last_tv_side:
                    side_sync = adopt_live_tv_side(
                        self,
                        reconcile,
                        adopted_manual=not bool(reconcile.get("open_log_qty")),
                    )
                    reconcile_notes.append(
                        f"方向校正: 实盘{side} ← TV{side_sync.get('previous_tv_side')} "
                        f"({side_sync.get('reason')})"
                    )
                    if side_sync.get("conflict"):
                        reconcile_notes.append("TV反向OPEN信号但信任实盘持仓")

                saved_initial = self._safe_qty(self.initial_qty)
                open_log_qty = self._safe_qty(reconcile.get("open_log_qty") or 0)
                restored = max(saved_initial, open_log_qty, real_amt)
                self.watched_qty = real_amt
                if restored > real_amt:
                    self.initial_qty = restored
                elif saved_initial <= 0:
                    self.initial_qty = real_amt
                else:
                    self.initial_qty = saved_initial
                if float(getattr(self, "base_qty", 0) or 0) <= 0:
                    self.base_qty = float(open_log_qty or real_amt)
                if int(getattr(self, "add_count", 0) or 0) <= 0 and self.base_qty > 0:
                    ratio = float(getattr(settings, "ADD_QTY_RATIO", 0.5) or 0.5)
                    if real_amt > self.base_qty and ratio > 0:
                        inferred = int(round((real_amt - self.base_qty) / (self.base_qty * ratio)))
                        self.add_count = min(max(inferred, 0), self._max_add_times())
                self.watched_entry = float(pos["entry_price"])
                qty_change = reconcile.get("qty_manual_change")

                curr_px = self.client.get_current_price(self.symbol)
                self._refresh_radar_state_on_recover(curr_px, self.watched_entry)

                cap_result = self._enforce_regime_cap_alignment(
                    real_amt,
                    self.watched_entry,
                    curr_px or self.watched_entry,
                    reason="重启恢复",
                )
                if cap_result.get("new_qty"):
                    real_amt = self._safe_qty(cap_result["new_qty"])
                    self.watched_qty = real_amt

                curr_px = self.client.get_current_price(self.symbol) if hasattr(self.client, "get_current_price") else 0
                self._sync_consumed_tp_levels(real_amt, curr_px or self.watched_entry)

                unified = self._unified_startup_defense_reconcile(
                    real_amt,
                    self.watched_entry,
                    curr_px or self.watched_entry,
                    cap_result=cap_result,
                    reason="VPS/部署重启",
                )
                result = unified.get("tp_defense") or {}
                matched = unified.get("tp_matched", result.get("matched", 0))
                expected = unified.get("tp_expected", result.get("expected", 0))
                _rebuilt = unified.get("defenses_rebuilt", False)
                audit = result.get("audit") or {}
                self._last_startup_unified = unified

                radar_active = bool(unified.get("breakeven_active"))
                radar_sl = unified.get("radar_sl") or {}

                logger.info(
                    f"🔄 [系统重启点火] 检测到实盘持仓 {self.current_side} {real_amt}张 @ "
                    f"{self.watched_entry:.2f} | {unified.get('startup_summary', '')} | "
                    f"TV对齐 {self.last_tv_side} | 对账 {len(reconcile_notes)} 项"
                )

                self.monitoring = True
                self._save_state()
                self._ensure_price_ws()
                self._record_open_log(
                    self.current_side, real_amt, self.watched_entry, source="recover",
                )

                sl_ok = bool(radar_sl.get("live"))
                if not sl_ok and radar_active and self.current_sl > 0:
                    sl_ok = bool(self._ensure_radar_sl(real_amt, self.current_sl))
                    if sl_ok:
                        sl_ok = self._has_trigger_sl_near(self.current_sl)
                if radar_active or sl_ok:
                    logger.info(
                        f"📡 [重启] 雷达哨兵已点火 | SL={self.current_sl:.2f} | "
                        f"止损={'实盘✓' if sl_ok else '待哨兵补挂'}"
                    )

                threading.Thread(target=self._sentinel_loop, daemon=True).start()

                verified = self._verify_position(self.current_side)
                if verified and self._safe_qty(verified['size']) == real_amt:
                    tv_note = ""
                    if self.last_tv_signal:
                        tv_note = (
                            f" | 最新TV: {self.last_tv_signal.get('action')} "
                            f"@{self.last_tv_signal.get('ts', '')}"
                        )
                    reconcile_txt = (" | " + " ; ".join(reconcile_notes)) if reconcile_notes else ""
                    skip_note = (
                        " | 盘口已齐全，未重复补挂"
                        if unified.get("defenses_skipped") or not _rebuilt
                        else ""
                    )
                    startup_note = f" | {unified.get('startup_summary', '')}" if unified.get("startup_summary") else ""
                    verify_note = (
                        f"接管 {real_amt}张 @ {verified['entry_price']:.2f} | "
                        f"TV方向 {self.last_tv_side} | "
                        f"止盈 {matched}/{expected} 档 | "
                        f"{self._format_audit_summary(audit)}{startup_note}{skip_note}{tv_note}{reconcile_txt}"
                    )
                    self._dt.report_recover_takeover(
                        self.current_side, real_amt, verified['entry_price'],
                        self.tv_tps, self.regime, radar_active, self.current_sl,
                        verify_note=verify_note,
                        tp_matched=matched,
                        tp_expected=expected,
                        tp_audit=audit,
                        last_tv_signal=self.last_tv_signal,
                        radar_sl_ok=sl_ok,
                    )
                    if qty_change:
                        old_q, new_q, action_msg = qty_change
                        self._dt.report_manual_position_change(
                            action_msg, old_q, new_q, verified['entry_price'],
                            verify_note=(
                                f"重启接管检测 | {verify_note}"
                            ),
                            tp_audit=audit,
                        )
                    if expected > 0 and matched < expected:
                        self._dt.report_system_alert(
                            "重启接管后限价止盈未对齐",
                            f"{self.current_side} {real_amt}张 @ {verified['entry_price']:.2f} | "
                            f"仅 {matched}/{expected} 档 | {self._format_audit_summary(audit)} | "
                            f"请查 logs/deepcoin_brain.log",
                        )
                else:
                    logger.warning("重启接管钉钉跳过：实盘核查未通过")
                logger.info("  -> 🎉 实盘阵地接管完毕，TP123 及雷达系统已复位。")
            else:
                self.client.cancel_all_open_orders(self.symbol)
                logger.info("🔄 [系统重启点火] 盘口干净无持仓，账本复位为空仓待命。")
                self.monitoring = False
                self.watched_qty = 0
                self.initial_qty = 0
                self.base_qty = 0
                self.add_count = 0
                self.current_side = None
                self._save_state()
        except Exception as e:
            logger.error(f"❌ 闪电接管异常: {e}")
            self._dt.report_system_alert("重启接管失败", str(e))

    def recover_on_startup(
        self,
        open_trade_id: int | None = None,
        recovery_context: dict | None = None,
    ) -> dict:
        """Gemini dispatcher entry — wraps legacy recover_state_on_startup."""
        audit: dict = {
            "user_id": self.user_id,
            "exchange": "deepcoin",
            "has_position": False,
            "side": None,
            "qty": 0.0,
            "entry": 0.0,
            "monitoring": False,
            "defenses_skipped": False,
            "defenses_rebuilt": False,
            "open_trade_id": open_trade_id,
            "tv_tps": list(self.tv_tps),
        }
        if recovery_context:
            trade = recovery_section(recovery_context, "trade")
            open_log = recovery_section(recovery_context, "open_log")
            latest_tv = recovery_section(recovery_context, "latest_tv")
            reconcile = self._reconcile_radar_context(recovery_context)
            audit.update(reconcile)
            open_qty = float(open_log.get("qty") or trade.get("quantity") or 0)
            if open_qty > 0:
                self.initial_qty = max(float(self.initial_qty or 0), open_qty)
            for src in (trade, open_log, latest_tv):
                if src.get("tv_tps"):
                    self.tv_tps = [float(x) for x in src["tv_tps"][:3]]
                if src.get("regime"):
                    self.regime = clamp_regime(src["regime"])
                if src.get("side"):
                    self.last_tv_side = str(src["side"]).upper()
        try:
            self.recover_state_on_startup()
            pos = self._get_active_position()
            has_pos = bool(pos and self._safe_qty(pos.get("size")) > 0)
            audit.update({
                "has_position": has_pos,
                "side": self.current_side,
                "qty": float(self.watched_qty or 0),
                "entry": float(self.watched_entry or 0),
                "monitoring": self.monitoring,
                "defenses_skipped": has_pos and self.monitoring,
                "defenses_rebuilt": has_pos and self.monitoring,
                "tv_tps": list(self.tv_tps),
                "current_sl": self.current_sl,
                "best_price": self.best_price,
                "consumed_tp_levels": list(self.consumed_tp_levels or []),
                "initial_qty": float(self.initial_qty or 0),
            })
            unified = getattr(self, "_last_startup_unified", None) or {}
            if unified:
                audit.update({
                    "pnl_track": unified.get("pnl_track"),
                    "startup_summary": unified.get("startup_summary"),
                    "breakeven_active": unified.get("breakeven_active"),
                    "radar_sl": unified.get("radar_sl"),
                    "radar_progress": unified.get("radar_progress"),
                    "tp_matched": unified.get("tp_matched"),
                    "tp_expected": unified.get("tp_expected"),
                    "defenses_aligned": unified.get("defenses_aligned"),
                })
        except Exception as e:
            logger.error("[User %s] deepcoin recover failed: %s", self.user_id, e)
            audit["error"] = str(e)
            self._alert("critical", "STARTUP_FAIL", "深币自启接管失败", str(e), audit)
        return audit

