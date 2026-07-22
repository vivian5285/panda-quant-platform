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
from app.core.radar_trail import clamp_stop_market_safe, tp_path_progress
from app.core.vps_radar_stages import (
    tp1_filled_from_consumed,
)
from app.core.tp_regime_targets import build_regime_settings, enrich_tp_alert_detail
from app.core.same_direction_policy import (
    SameDirAction,
    evaluate_same_direction,
    format_refresh_reason,
    format_reopen_reason,
)
from app.core.position_sizing import read_contract_equity
from app.core.tv_entry_sizing import (
    parse_tv_entry_fields,
    resolve_vps_entry_qty_deepcoin,
)
from app.core.position_qty_tolerance import qty_change_significant
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
from app.core.tp_slice_guard import (
    compute_tp_slices,
    infer_filled_tp_levels,
    match_qty_reduction_to_tp_level,
    resolve_tp_step_fill_level,
)
from app.core.position_qty_tolerance import tp_slice_qty_tolerance
from app.core.position_cap_guard import PositionCapGuardMixin
from app.core.adverse_radar_guard import AdverseRadarMixin, ADVERSE_STOP_TOLERANCE
from app.core.startup_reconcile import (
    StartupReconcileMixin,
    apply_tv_sl_from_sources,
    finalize_recovery_tv_params,
    format_startup_defense_summary,
    is_tv_close_action,
    prepare_manual_adopt,
    recovery_section,
    should_ignore_bare_close_after_open,
    should_skip_tv_close_for_manual,
)
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

DEEPCOIN_SUPERVISOR_VERSION = "v13.4.7-ws-radar"
SENTINEL_POLL_NORMAL = 5.0
# Align with Binance/OKX/Gate — TP1/TP2 order monitor cadence (checklist §4.2 / 拍板)
SENTINEL_POLL_ARMING = 0.5
SENTINEL_POLL_RADAR = 0.5
RADAR_WS_TICK_MIN_SEC = 0.45
DUST_ORPHAN_CONTRACTS = 1
TP_COMPLETE_RESIDUAL_RATIO = 0.12
FLAT_WAIT_TIMEOUT = 12.0
FLAT_WAIT_POLL = 0.6


class _DingtalkBridge:
    """Route legacy dingtalk report_* calls to Gemini on_alert.

    Map known report_* names onto ADMIN_DINGTALK_KEY_TYPES so Open / radar /
    close alerts actually push (bare REPORT_* names were silently dropped).
    """

    _TYPE_MAP = {
        "report_supervisor_open": ("OPEN", "info", "GEMINI开仓"),
        "report_supervisor_close": ("CLOSE", "info", "全平完成"),
        "report_intervention": ("TRAIL", "info", "雷达追踪"),
        "report_system_alert": ("SENTINEL_ERROR", "warning", "系统告警"),
        "report_force_align": ("FORCE_ALIGN", "critical", "方向背离"),
        "report_close": ("CLOSE", "info", "全平完成"),
        "report_recover_takeover": ("STARTUP", "info", "重启接管"),
        "report_manual_position_change": ("MANUAL_ADJUST", "warning", "人工调仓"),
    }

    def __init__(self, supervisor: "DeepcoinPositionSupervisor"):
        self._sup = supervisor

    def __getattr__(self, name: str):
        def _call(*args, **kwargs):
            mapped = self._TYPE_MAP.get(name)
            if mapped:
                alert_type, severity, title = mapped
            else:
                title = name.replace("report_", "").replace("_", " ").title()
                alert_type = name.upper()
                severity = (
                    "critical" if "fail" in name or "force" in name
                    else "warning" if "alert" in name or "intervention" in name
                    else "info"
                )
            msg_parts = [str(a) for a in args if a is not None]
            message = " | ".join(msg_parts)[:500] if msg_parts else title
            detail = dict(kwargs) if kwargs else {}
            # Prefer explicit kwargs title/type when callers pass them
            if kwargs.get("alert_type"):
                alert_type = str(kwargs["alert_type"])
            if kwargs.get("title"):
                title = str(kwargs["title"])
            self._sup._alert(severity, alert_type, title, message, detail)

        return _call

    def report_supervisor_open(self, *args, **kwargs):
        """OPEN with exchange theme title (pushes DingTalk)."""
        from app.services.trading_alerts import resolve_exchange_theme

        lev = kwargs.get("leverage") or getattr(self._sup, "leverage", None)
        theme = resolve_exchange_theme(
            "deepcoin",
            getattr(self._sup, "canonical_symbol", None),
            leverage=lev,
        )
        side = args[0] if args else kwargs.get("side", "")
        entry = args[1] if len(args) > 1 else kwargs.get("entry", 0)
        qty = args[3] if len(args) > 3 else kwargs.get("qty", 0)
        verify_note = kwargs.get("verify_note") or ""
        detail = {k: v for k, v in kwargs.items() if k not in ("verify_note", "title", "alert_type")}
        detail.setdefault("exchange", "deepcoin")
        detail.setdefault("side", side)
        detail.setdefault("entry", entry)
        detail.setdefault("qty", qty)
        detail.setdefault("radar_armed", False)
        detail.setdefault("entry_type", "OPEN")
        if lev:
            detail["leverage"] = int(lev)
        title = (
            f"{theme['accent']} GEMINI开仓 · "
            f"{theme.get('symbol_label') or getattr(self._sup, 'canonical_symbol', '')} "
            f"· {theme['label']} 档位{getattr(self._sup, 'regime', '')} · {theme['leverage']}×"
        )
        message = (
            f"{getattr(self._sup, 'canonical_symbol', '')} {side} {qty} 张 @ {entry} | "
            f"TV杠杆{theme['leverage']}× | {verify_note}"
        ).strip(" |")
        self._sup._alert("info", "OPEN", title, message, detail)
        if hasattr(self._sup, "_reconcile_live_vs_book"):
            self._sup._reconcile_live_vs_book(
                expect_side=str(side).upper() if side else None,
                expect_qty=float(qty or 0) or None,
                context="open",
                notify_ok=True,
            )

class DeepcoinPositionSupervisor(PositionCapGuardMixin, AdverseRadarMixin, StartupReconcileMixin):
    TP_RETRY_MAX = 3
    TP_RETRY_DELAY = 0.8

    def __init__(
        self,
        user_id: int,
        client: DeepcoinClient,
        initial_principal: float = 0.0,
        canonical_symbol: str | None = None,
        on_log: Optional[Callable] = None,
        on_trade_open: Optional[Callable] = None,
        on_trade_close: Optional[Callable] = None,
        on_trade_update_targets: Optional[Callable] = None,
        on_alert: Optional[Callable] = None,
    ):
        from app.core.symbol_registry import (
            DEFAULT_CANONICAL,
            exchange_native_symbol,
            label_for_symbol,
            normalize_canonical_symbol,
            qty_unit_for_symbol,
            supervisor_state_key,
        )

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

        self.canonical_symbol = (
            normalize_canonical_symbol(canonical_symbol)
            or getattr(client, "canonical_symbol", None)
            or DEFAULT_CANONICAL
        )
        self.symbol = getattr(client, "trading_symbol", None) or exchange_native_symbol(
            "deepcoin", self.canonical_symbol
        )
        self.qty_unit = qty_unit_for_symbol(self.canonical_symbol, "deepcoin")
        self.symbol_label = label_for_symbol(self.canonical_symbol)
        self.monitoring = False
        self._lock = threading.Lock()

        self.regime_settings = build_regime_settings()
        from app.core.tv_entry_sizing import FIXED_LEVERAGE
        self.leverage = int(
            getattr(client, "trading_leverage", None) or FIXED_LEVERAGE
        )
        self.face_value = 0.1

        self.regime = 3
        self.risk_multiplier = 1.0
        self.current_atr = 30.0
        self.initial_atr = 0.0
        self.initial_stop = 0.0
        self.breakeven_phase = False
        self.current_adx = 25.0
        self.remaining_qty_pct = 1.0
        self.best_price = 0.0
        self.radar_activated = False
        self.radar_step_count = 0
        self._atr_refreshed_at = 0.0
        self._tp_placed_at = {}
        self._defense_order_ids = {}
        self.current_sl = 0.0
        self.tv_price = 0.0
        self.tv_tps = [0.0, 0.0, 0.0]

        self.initial_qty = 0
        self.base_qty = 0
        self.add_count = 0
        self.consumed_tp_levels: list[int] = []
        self.adopted_manual = False
        self.watched_qty = 0
        self.watched_entry = 0.0
        self.current_side = None
        self.last_tv_side = None
        self.last_tv_signal = None
        self._scan_ticks = 0
        self._radar_ws_tick_ts: float = 0.0
        self._radar_ws_bound: bool = False
        self._signal_queue = queue.Queue()
        self._signal_worker_started = False
        self._init_adverse_radar_fields()

        state_key = supervisor_state_key("deepcoin", user_id, self.canonical_symbol)
        base_dir = os.path.join("data", "supervisor", state_key)
        os.makedirs(base_dir, exist_ok=True)
        self.state_file = os.path.join(base_dir, "state.json")
        self.tv_journal = os.path.join(base_dir, "tv_journal.jsonl")
        self.open_journal = os.path.join(base_dir, "open_journal.jsonl")
        # Migrate legacy deepcoin_{user_id}/ for ETH
        legacy_dir = os.path.join("data", "supervisor", f"deepcoin_{user_id}")
        if (
            self.canonical_symbol == DEFAULT_CANONICAL
            and not os.path.exists(self.state_file)
            and os.path.isdir(legacy_dir)
        ):
            for name in ("state.json", "tv_journal.jsonl", "open_journal.jsonl"):
                src = os.path.join(legacy_dir, name)
                dst = os.path.join(base_dir, name)
                if os.path.isfile(src) and not os.path.exists(dst):
                    try:
                        import shutil
                        shutil.copy2(src, dst)
                    except Exception:
                        pass

        logger.info(
            f"🧠 深币 Supervisor user={user_id} {self.canonical_symbol} "
            f"[{DEEPCOIN_SUPERVISOR_VERSION}/{CLIENT_VERSION}] 已加载"
        )
        self._start_signal_worker()
        self._start_idle_flat_patrol()

    def _read_live_position_snapshot(self):
        from app.core.position_supervisor import PositionSupervisor

        return PositionSupervisor._read_live_position_snapshot(self)

    def _reconcile_live_vs_book(self, **kwargs):
        from app.core.position_supervisor import PositionSupervisor

        return PositionSupervisor._reconcile_live_vs_book(self, **kwargs)

    def _start_idle_flat_patrol(self):
        """空仓待命时后台巡检：实盘对账 / 同向接管 / 残张扫尾"""
        from app.config import get_settings

        interval = float(get_settings().IDLE_PATROL_INTERVAL_SEC or 10.0)

        def loop():
            while True:
                time.sleep(interval)
                if self.monitoring:
                    continue
                if not self._lock.acquire(timeout=2.0):
                    continue
                try:
                    if self.monitoring:
                        continue
                    self._run_idle_live_watch()
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
        payload = dict(detail or {})
        can = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        if can:
            payload.setdefault("canonical_symbol", can)
            payload.setdefault("symbol", can)
        if getattr(self, "qty_unit", None):
            payload.setdefault("qty_unit", self.qty_unit)
        payload.setdefault("exchange", "deepcoin")
        if hasattr(self, "_resolve_entry_leverage"):
            try:
                payload["leverage"] = int(self._resolve_entry_leverage())
            except Exception:
                if int(getattr(self, "leverage", 0) or 0) > 0:
                    payload.setdefault("leverage", int(self.leverage))
        elif int(getattr(self, "leverage", 0) or 0) > 0:
            payload.setdefault("leverage", int(self.leverage))
        if getattr(self, "current_side", None):
            payload.setdefault("side", self.current_side)
        if float(getattr(self, "watched_qty", 0) or 0) > 0:
            payload.setdefault("qty", float(self.watched_qty))
        if float(getattr(self, "watched_entry", 0) or 0) > 0:
            payload.setdefault("entry", float(self.watched_entry))
        if float(getattr(self, "current_sl", 0) or 0) > 0:
            payload.setdefault("current_sl", float(self.current_sl))
        if getattr(self, "regime", None) is not None:
            payload.setdefault("regime", int(self.regime))
        self.on_alert(self.user_id, severity, alert_type, title, message, payload)

    @staticmethod
    def _call_dingtalk(fn, **kwargs):
        """兼容 VPS 旧版 self._dt.py（缺少 verified / swept_dust 等新参数）"""
        try:
            fn(**kwargs)
            return
        except TypeError as exc:
            msg = str(exc)
            legacy = None
            # Strip unknown kwargs and retry (legacy report_* signatures vary)
            if "unexpected keyword argument" in msg or "got an unexpected keyword" in msg:
                import inspect
                try:
                    sig = inspect.signature(fn)
                    allowed = {
                        p.name for p in sig.parameters.values()
                        if p.kind in (
                            inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            inspect.Parameter.KEYWORD_ONLY,
                        )
                    }
                    has_var_kw = any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in sig.parameters.values()
                    )
                    if has_var_kw:
                        raise  # accepts **kwargs — original error is elsewhere
                    legacy = {k: v for k, v in kwargs.items() if k in allowed}
                except (TypeError, ValueError):
                    legacy = {
                        k: v for k, v in kwargs.items()
                        if k not in ("verified", "swept_dust", "verify_note", "alert_type", "title")
                    }
                logger.warning(
                    "钉钉旧版降级播报 %s: %s | dropped=%s",
                    getattr(fn, "__name__", "dingtalk"),
                    exc,
                    sorted(set(kwargs) - set(legacy or {})),
                )
                if legacy:
                    try:
                        fn(**legacy)
                        return
                    except TypeError as exc2:
                        msg = str(exc2)
                        exc = exc2
                else:
                    # No overlapping kwargs — fall through to positional fallback
                    msg = "missing required positional argument"
            # Missing required positional — try reason-only / message-only fallbacks
            if (
                "required positional" in msg
                or "missing" in msg.lower()
                or "unexpected keyword" in msg
            ):
                for key in ("reason", "message", "title", "verify_note"):
                    if key in kwargs:
                        try:
                            fn(kwargs[key])
                            logger.warning(
                                "钉钉参数降级(positional) %s via %s: %s",
                                getattr(fn, "__name__", "dingtalk"), key, exc,
                            )
                            return
                        except TypeError:
                            continue
            raise

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
                reconcile["latest_tv_action"] = tv_action
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
                    f"TV最新为{tv_action} ({last_tv.get('ts', '')})，实盘仍有仓"
                )
                if last_open_tv:
                    open_action = (last_open_tv.get("action") or "").upper()
                    self.last_tv_side = open_action
                    open_tps = self._sanitize_tp_prices(last_open_tv.get("tv_tps", []))
                    if sum(1 for t in open_tps if t > 0) > 0:
                        self.tv_tps = open_tps
                    if side == open_action:
                        reconcile["tv_close"] = False
                        notes.append("TV CLOSE 但实盘同向 → 接管补挂不 flatten")
                elif last_open and (last_open.get("side") or "").upper() == side:
                    reconcile["tv_close"] = False
                    self.last_tv_side = side
                    notes.append("TV CLOSE 但开仓日志同向 → 接管补挂不 flatten")
                elif side == self.last_tv_side:
                    reconcile["tv_close"] = False
                    notes.append("TV CLOSE 但实盘与 last_tv_side 同向 → 接管")

        if not self.last_tv_side and last_open_tv:
            self.last_tv_side = (last_open_tv.get("action") or "").upper()

        if last_open:
            open_side = last_open.get("side")
            open_qty = self._safe_qty(last_open.get("qty") or 0)
            if open_qty > 0:
                reconcile["open_log_qty"] = open_qty
            if open_side:
                reconcile["open_log_side"] = str(open_side).upper()
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
                    "schema_version": 2,
                    "last_tv_side": self.last_tv_side,
                    "current_side": self.current_side,
                    "watched_qty": self.watched_qty,
                    "watched_entry": self.watched_entry,
                    "current_sl": self.current_sl,
                    "monitoring": self.monitoring,
                    "regime": self.regime,
                    "current_atr": self.current_atr,
                    "initial_atr": float(getattr(self, "initial_atr", 0) or 0),
                    "initial_stop": float(getattr(self, "initial_stop", 0) or 0),
                    "breakeven_phase": bool(getattr(self, "breakeven_phase", False)),
                    "current_adx": float(getattr(self, "current_adx", 25) or 25),
                    "remaining_qty_pct": float(getattr(self, "remaining_qty_pct", 1.0) or 1.0),
                    "tv_tps": self.tv_tps,
                    "tv_price": self.tv_price,
                    "best_price": self.best_price,
                    "initial_qty": self.initial_qty,
                    "base_qty": float(getattr(self, "base_qty", 0) or 0),
                    "add_count": 0,
                    "consumed_tp_levels": list(self.consumed_tp_levels),
                    "last_tv_signal": self.last_tv_signal,
                    "adverse_sl_armed": self.adverse_sl_armed,
                    "adverse_sl_prices": self.adverse_sl_prices,
                    "adverse_consumed_tiers": list(self.adverse_consumed_tiers),
                    "adverse_arm_dingtalk_sent": bool(getattr(self, "adverse_arm_dingtalk_sent", False)),
                    "adverse_last_repair_ts": float(getattr(self, "_adverse_last_repair_ts", 0) or 0),
                    "tv_sl": float(getattr(self, "tv_sl", 0) or 0),
                    "tv_stop_loss_ref": float(getattr(self, "_tv_stop_loss_ref", 0) or 0),
                    "tv_hard_sl_price": float(
                        getattr(self, "_tv_hard_sl_price", 0)
                        or getattr(self, "current_sl", 0)
                        or 0
                    ),
                    "leverage": int(getattr(self, "leverage", 0) or 0),
                    "tv_entry_fields": dict(getattr(self, "_tv_entry_fields", None) or {}),
                    "adopted_manual": bool(getattr(self, "adopted_manual", False)),
                    "radar_latched": bool(getattr(self, "radar_latched", False)),
                    "radar_activated": bool(getattr(self, "radar_activated", False)),
                    "radar_step_count": int(getattr(self, "radar_step_count", 0) or 0),
                    "tp_placed_at": dict(getattr(self, "_tp_placed_at", None) or {}),
                    "defense_order_ids": dict(getattr(self, "_defense_order_ids", None) or {}),
                    "trading_paused": bool(getattr(self, "trading_paused", False)),
                    "trading_pause_reason": str(getattr(self, "trading_pause_reason", "") or ""),
                    "current_trade_id": getattr(self, "current_trade_id", None),
                    "canonical_symbol": getattr(self, "canonical_symbol", None),
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

    def _handle_position_query_failure(self, err):
        from datetime import datetime, timezone
        from app.core.exchange_errors import ExchangeTransientError

        already = bool(getattr(self, "_position_query_degraded", False))
        self._position_query_degraded = True
        self._position_query_error = str(err)[:500]
        ban_ms = getattr(err, "banned_until_ms", None) if isinstance(err, ExchangeTransientError) else None
        detail = {
            "exchange": "deepcoin",
            "symbol": getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None),
            "error": str(err)[:400],
            "watched_qty": self._safe_qty(getattr(self, "watched_qty", 0)),
            "current_side": getattr(self, "current_side", None),
            "kept_last_known": True,
            "auto_flat_judgment_paused": True,
        }
        if ban_ms:
            try:
                detail["banned_until_utc"] = datetime.fromtimestamp(
                    ban_ms / 1000.0, tz=timezone.utc,
                ).isoformat()
            except (OSError, OverflowError, ValueError):
                detail["banned_until_ms"] = ban_ms
        logger.error(
            "position query failed — keep book qty=%s side=%s | %s",
            detail["watched_qty"], detail["current_side"], err,
        )
        if already:
            return
        if hasattr(self, "_alert"):
            self._alert(
                "critical",
                "EXCHANGE_QUERY_FAIL",
                "交易所仓位查询失败·已暂停自动空仓判断",
                "API 失败不得当作空仓；保留上次已知持仓，待查询恢复后再判断",
                detail,
            )

    def _clear_position_query_degraded(self):
        if not getattr(self, "_position_query_degraded", False):
            return
        self._position_query_degraded = False
        self._position_query_error = ""
        logger.info("position query recovered — auto flat judgment resumed")
        if hasattr(self, "_alert"):
            self._alert(
                "info",
                "EXCHANGE_QUERY_OK",
                "交易所仓位查询已恢复",
                "自动空仓/对账判断已恢复",
                {"exchange": "deepcoin", "symbol": getattr(self, "symbol", None)},
            )

    def _get_active_position(self):
        from app.core.exchange_errors import ExchangeTransientError

        try:
            res = self.client.get_position_info(self.symbol)
        except ExchangeTransientError as e:
            self._handle_position_query_failure(e)
            raise
        self._clear_position_query_degraded()
        if res and "data" in res:
            for p in res["data"]:
                if self._safe_qty(p.get("pos")) > 0:
                    return {
                        "size": self._safe_qty(p.get("pos")),
                        "entry_price": round(float(p.get("avgPx", p.get("price", 0)) or 0), 2),
                        "posSide": p.get("posSide", "long").lower(),
                    }
        return None

    def _verify_flat(self):
        from app.core.exchange_errors import ExchangeTransientError

        try:
            pos = self._get_active_position()
        except ExchangeTransientError:
            return False
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

        pnl_source = "mark_estimate"
        try:
            from app.services.exchange_fill_sync import fetch_live_eth_fills, sum_realized_from_fills
            start_ms = int(self.trade_opened_at * 1000) if getattr(self, "trade_opened_at", None) else None
            fills = fetch_live_eth_fills(self.client, "deepcoin", start_time_ms=start_ms)
            fill_pnl = sum_realized_from_fills(fills, start_ms=start_ms)
            if fills:
                pnl = float(fill_pnl)
                pnl_source = "exchange_fills"
        except Exception as exc:
            logger.warning("deepcoin close fill pnl lookup failed: %s", exc)

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
        close_detail["pnl_source"] = pnl_source
        if tv_pnl_pct is not None:
            close_detail["tv_pnl_pct"] = round(float(tv_pnl_pct), 2)
        if tv_side and side and tv_side != side:
            close_detail["tv_side_mismatch"] = True

        tid = trade_id_snapshot or self.current_trade_id
        if tid and exit_price > 0:
            self.on_trade_close(tid, exit_price, pnl, display_reason, 0.0)

        attribution = close_detail.get("attribution") if isinstance(close_detail.get("attribution"), dict) else None
        alert_type = resolve_close_alert_type(close_action, display_reason, attribution)
        alert_title = resolve_close_alert_title(close_action, display_reason, attribution)
        ding_head = display_reason
        if attribution and not close_action:
            ding_head = attribution.get("human_reason") or display_reason
        ding_msg = format_close_dingtalk_message(ding_head, verify_note)
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
        if hasattr(self, "_clear_position_local_state"):
            self._clear_position_local_state()
        else:
            self.watched_qty = 0
            self.watched_entry = 0.0
            self.initial_qty = 0
            self.base_qty = 0
            self.add_count = 0
            self.current_side = None
            self.best_price = 0.0
        self._save_state()
        self._purge_defense_orders_on_flat("dust_sweep", notify=True)
        self._report_flat_close(reason, swept_dust=True)

    def _scan_and_sweep_dust_on_startup(self):
        """重启首检：发现蚂蚁仓/止盈残张 → 扫尾收网，避免误接管为正常持仓"""
        pos = self._get_active_position()
        if not pos or self._safe_qty(pos.get("size")) <= 0:
            return False
        if not self.current_side:
            self.current_side = "LONG" if pos.get("posSide") == "long" else "SHORT"
        real_amt = self._safe_qty(pos["size"])
        if not self._is_dust_qty(real_amt):
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
        from app.core.exchange_errors import ExchangeTransientError

        try:
            pos = self._get_active_position()
        except ExchangeTransientError:
            logger.error(
                "skip flat reconcile on startup — position query unavailable (keeping book)"
            )
            return False
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
        self._purge_defense_orders_on_flat("startup_reconcile", notify=True)
        self.monitoring = False
        if hasattr(self, "_clear_position_local_state"):
            self._clear_position_local_state()
        else:
            self.watched_qty = 0
            self.watched_entry = 0.0
            self.initial_qty = 0
            self.base_qty = 0
            self.add_count = 0
            self.current_side = None
            self.best_price = 0.0
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

    def _flat_purge_side_snapshot(self):
        snap = getattr(self, "_flat_purge_side", None)
        if snap in ("LONG", "SHORT"):
            return snap
        side = getattr(self, "current_side", None)
        return side if side in ("LONG", "SHORT") else None

    def _is_flat_orphan_tp_order(self, o, side=None):
        if o.get("ordType") not in ("limit", "post_only", None):
            return False
        val = o.get("reduceOnly")
        if val is True or str(val).lower() in ("true", "1"):
            return True
        side = side or self._flat_purge_side_snapshot()
        if not side:
            return False
        close_side = "sell" if side == "LONG" else "buy"
        if str(o.get("side", "")).lower() != close_side:
            return False
        px = float(o.get("px", 0) or 0)
        if px <= 0:
            return False
        tv_tps = list(getattr(self, "tv_tps", []) or [])
        if tv_tps:
            return any(tp_price_matches(px, t) for t in tv_tps if t > 0)
        return True

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
        """Fixed 30/30/40 slices; only TP1+TP2 placeable (ignore TV qty*)."""
        from app.core.tp_regime_targets import pine_tp_ratios_frac

        ratios = pine_tp_ratios_frac()
        settings = dict(self.regime_settings)
        r = int(self.regime or 3)
        row = dict(settings.get(r) or settings.get(3) or {})
        row["ratios"] = ratios
        settings[r] = row
        return compute_tp_slices(
            float(qty),
            r,
            self.tv_tps,
            settings,
            exclude_levels=exclude_levels or set(),
            round_qty_fn=lambda x: float(max(self._safe_qty(x), 1)),
            min_qty=1.0,
        )

    def _sync_consumed_tp_levels(self, live_qty, curr_px):
        from app.core.tp_slice_guard import compute_tp_slices, levels_past_by_mark

        anchor = float(self._safe_qty(self.initial_qty or live_qty))
        live = float(self._safe_qty(live_qty))
        tol = tp_slice_qty_tolerance(anchor, is_contracts=True)
        slices = compute_tp_slices(
            anchor, self.regime, self.tv_tps, self.regime_settings, exclude_levels=set(),
        )
        tp1_slice = float(slices[0][1]) if slices else 0.0
        past_early = levels_past_by_mark(
            float(curr_px or 0),
            self.current_side,
            list(self.tv_tps or []),
            peak_px=float(getattr(self, "best_price", 0) or 0),
        )
        # 手数噪声带（1 张）；仅当盘口仍挂着对应 TP 限价时才清误记账。
        # 超时撤单后 live==anchor 且盘口已空 → 必须保留 consumed，禁止核武重挂循环。
        restore_tol = 1.0
        if (
            tp1_slice > 0
            and abs(live - anchor) <= restore_tol
            and self.consumed_tp_levels
            and not past_early
        ):
            open_prices = [float(o.get("price", 0)) for o in self._collect_tp_limit_orders()]
            still_on_book = False
            for lvl in list(self.consumed_tp_levels or []):
                try:
                    idx = int(lvl) - 1
                    tp_px = float((self.tv_tps or [0, 0, 0])[idx] or 0) if idx >= 0 else 0.0
                except (TypeError, ValueError, IndexError):
                    tp_px = 0.0
                if tp_px > 0 and any(abs(float(p) - tp_px) <= 0.05 for p in open_prices):
                    still_on_book = True
                    break
            if still_on_book:
                logger.warning("仓位仍满且 TP 限价仍在盘口，清除误记账 %s", self.consumed_tp_levels)
                self.consumed_tp_levels = []
                if hasattr(self, "_tp_fill_dingtalk_levels"):
                    self._tp_fill_dingtalk_levels = set()
                if hasattr(self, "_save_state"):
                    self._save_state()
                return []
            logger.info(
                "满仓但 consumed=%s 且盘口无对应 TP → 保留记账（超时移交，禁止重挂）",
                self.consumed_tp_levels,
            )
        open_prices = [float(o.get("price", 0)) for o in self._collect_tp_limit_orders()]
        inferred = infer_filled_tp_levels(
            live,
            float(curr_px or 0),
            self.current_side,
            initial_qty=anchor,
            consumed_tp_levels=self.consumed_tp_levels,
            regime=self.regime,
            tv_tps=self.tv_tps,
            regime_settings=self.regime_settings,
            open_tp_prices=open_prices,
            qty_tol=tol,
            is_contracts=True,
            peak_px=float(getattr(self, "best_price", 0) or 0),
        )
        prev = {int(x) for x in (self.consumed_tp_levels or []) if int(x) in (1, 2, 3)}
        merged = sorted(
            prev
            | {int(x) for x in inferred if int(x) in (1, 2, 3)}
            | {int(x) for x in past_early if int(x) in (1, 2, 3)}
        )
        if merged != sorted(self.consumed_tp_levels or []):
            logger.info(
                "TP 已成交/已过价档位更新: %s → %s | past=%s",
                self.consumed_tp_levels, merged, sorted(past_early),
            )
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
        """与币安一致：当前盘口切片 + 开仓锚 + 盘口证据识别 TP 吃单。"""
        from app.core.tp_slice_guard import compute_tp_slices, tp_limit_still_on_book
        from app.core.position_supervisor import PositionSupervisor

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
        open_prices = [float(o.get("price", 0)) for o in self._collect_tp_limit_orders()]
        px = float(curr_px or 0)
        level = resolve_tp_step_fill_level(
            old_qty=old_qty,
            new_qty=new_qty,
            initial_qty=anchor,
            regime=self.regime,
            tv_tps=list(self.tv_tps or []),
            regime_settings=self.regime_settings,
            consumed_levels=self.consumed_tp_levels,
            curr_px=px,
            side=self.current_side,
            open_tp_prices=open_prices,
            is_contracts=True,
            peak_px=float(getattr(self, "best_price", 0) or 0),
        )
        if level is not None:
            if level not in self.consumed_tp_levels:
                self.consumed_tp_levels.append(level)
            if hasattr(self, "_save_state"):
                self._save_state()
            PositionSupervisor._notify_tp_fill_detected(self, level, old_qty, new_qty, px)
            return f"tp{level}_filled"

        before = set(int(x) for x in (self.consumed_tp_levels or []))
        sync_px = px if px > 0 else float(self.client.get_current_price(self.symbol) or 0)
        self._sync_consumed_tp_levels(new_qty, sync_px)
        after = set(int(x) for x in (self.consumed_tp_levels or []))
        gained = sorted(after - before)
        if gained:
            PositionSupervisor._notify_tp_fill_detected(self, gained[0], old_qty, new_qty, sync_px)
            return f"tp{gained[0]}_filled"

        if anchor > 0:
            from app.core.tp_slice_guard import price_reached_tp

            slices = compute_tp_slices(
                anchor, self.regime, self.tv_tps, self.regime_settings, exclude_levels=set(),
            )
            if slices:
                tp1_lvl, tp1_qty, tp1_px = slices[0]
                peak = float(getattr(self, "best_price", 0) or 0)
                px_ok = price_reached_tp(sync_px, tp1_px, self.current_side) or (
                    peak > 0 and price_reached_tp(peak, tp1_px, self.current_side)
                )
                if (
                    tp1_lvl == 1
                    and 1 not in after
                    and px_ok
                    and not tp_limit_still_on_book(tp1_px, open_prices)
                    and reduced + 1e-12 >= float(tp1_qty) * 0.5
                ):
                    self.consumed_tp_levels = sorted(after | {1})
                    if hasattr(self, "_save_state"):
                        self._save_state()
                    PositionSupervisor._notify_tp_fill_detected(
                        self, 1, old_qty, new_qty, sync_px, heuristic=True,
                    )
                    return "tp1_filled"
        return "manual_reduce"

    def _reconcile_radar_context(self, recovery: dict | None) -> dict:
        """Gemini 重启：OPEN 日志 + DB 交易 + 最新 TV 三方核实（与币安对齐）。"""
        report: dict = {"sources": [], "warnings": list(recovery.get("checks") or []) if recovery else []}
        if not recovery:
            return report

        trade = recovery_section(recovery, "trade")
        open_log = recovery_section(recovery, "open_log")
        latest_tv = recovery_section(recovery, "latest_tv")
        entry_tv = recovery_section(recovery, "latest_entry_tv")

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

            elif tv_action.startswith("CLOSE"):
                report["warnings"].append("tv_close_while_position")
                if entry_tv and (entry_tv.get("action") or "").upper() in ("LONG", "SHORT"):
                    report["latest_entry_tv_action"] = entry_tv.get("action")
                    self.last_tv_side = (entry_tv.get("action") or "").upper()

        finalize_recovery_tv_params(self, report, recovery)

        report["last_tv_side"] = self.last_tv_side
        report["tv_tps"] = list(self.tv_tps)
        report["regime"] = self.regime
        if open_log.get("side"):
            self._open_log_side = open_log.get("side")
        return report

    def _expected_tp_count(self, tp_pxs=None):
        live_qty = float(self._safe_qty(self.watched_qty))
        if live_qty <= 0:
            tp_pxs = tp_pxs if tp_pxs is not None else self.tv_tps
            return sum(1 for t in tp_pxs if t > 0)
        px = self._current_tp_price()
        exclude = self._active_tp_exclude_levels(live_qty, px)
        return len(self._compute_tp_slices(live_qty, exclude_levels=exclude))

    def _infer_filled_tp_levels(self, qty: float, curr_px: float) -> set[int]:
        """推断已成交 TP 档位（state 记录 + 开仓量对比 + 价格越过且无挂单）。"""
        from app.core.tp_slice_guard import levels_past_by_mark

        anchor = float(self.initial_qty or qty)
        tol = tp_slice_qty_tolerance(anchor, is_contracts=True)
        open_prices = [float(o.get("price", 0)) for o in self._collect_tp_limit_orders()]
        filled = infer_filled_tp_levels(
            qty,
            curr_px,
            self.current_side,
            initial_qty=anchor,
            consumed_tp_levels=self.consumed_tp_levels,
            regime=self.regime,
            tv_tps=self.tv_tps,
            regime_settings=self.regime_settings,
            open_tp_prices=open_prices,
            qty_tol=tol,
            is_contracts=True,
            peak_px=float(getattr(self, "best_price", 0) or 0),
        )
        past = levels_past_by_mark(
            float(curr_px or 0),
            self.current_side,
            list(self.tv_tps or []),
            peak_px=float(getattr(self, "best_price", 0) or 0),
        )
        return set(filled) | set(past)

    def _active_tp_exclude_levels(self, qty: float, curr_px: float) -> set[int]:
        """Exclude filled + mark-past levels; only PLACEABLE_TP_LEVELS hung."""
        from app.core.tp_slice_guard import should_skip_rehang_tp_level, SKIP_REHANG_HARD
        from app.core.tp_regime_targets import PLACEABLE_TP_LEVELS

        exclude = self._infer_filled_tp_levels(qty, curr_px)
        for lvl in (1, 2, 3):
            if lvl not in PLACEABLE_TP_LEVELS:
                exclude.add(lvl)
        open_prices = [float(o.get("price", 0) or 0) for o in self._collect_tp_limit_orders()]
        for i, tp_px in enumerate(list(self.tv_tps or [])[:3]):
            level = i + 1
            if level in exclude:
                continue
            skip, reason = should_skip_rehang_tp_level(
                level,
                float(tp_px or 0),
                side=self.current_side,
                curr_px=float(curr_px or 0),
                consumed=exclude,
                live_qty=float(qty or 0),
                initial_qty=float(self.initial_qty or qty or 0),
                regime=int(self.regime or 3),
                tv_tps=list(self.tv_tps or []),
                regime_settings=self.regime_settings,
                open_tp_prices=open_prices,
                is_contracts=True,
                peak_px=float(getattr(self, "best_price", 0) or 0),
            )
            if skip and reason in SKIP_REHANG_HARD:
                exclude.add(level)
        return exclude

    def _expected_tp_levels(self, live_qty, curr_px=None):
        live_qty = float(self._resolve_live_qty(live_qty))
        px = float(curr_px or 0)
        if px <= 0:
            px = self._current_tp_price()
        self._sync_consumed_tp_levels(live_qty, px)
        exclude = self._active_tp_exclude_levels(live_qty, px)
        normalized = {int(x) for x in exclude if int(x) in (1, 2, 3)}
        if normalized != {int(x) for x in (self.consumed_tp_levels or []) if int(x) in (1, 2, 3)}:
            self.consumed_tp_levels = sorted(normalized)
            if hasattr(self, "_save_state"):
                self._save_state()
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
        from app.core.tp_slice_guard import should_skip_rehang_tp_level

        price_tol = TP_PRICE_MATCH_TOL if tolerance is None else float(tolerance)
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"
        live_qty = self._resolve_live_qty(live_qty)
        if curr_px is None and hasattr(self.client, "get_current_price"):
            try:
                curr_px = float(self.client.get_current_price(self.symbol) or 0)
            except Exception:
                curr_px = 0.0
        px_now = float(curr_px or 0)
        self._sync_consumed_tp_levels(live_qty, px_now)
        self._cancel_tp_orders_for_consumed_levels()
        levels = self._expected_tp_levels(live_qty, curr_px)
        placed = 0
        open_prices = [float(o.get("price", 0) or 0) for o in self._collect_tp_limit_orders()]
        consumed = self._consumed_tp_level_set()

        for lv in levels:
            q, px = int(lv["qty"]), float(lv["price"])
            level = int(lv.get("level") or 0)
            if q <= 0 or px <= 0:
                continue
            skip, skip_reason = should_skip_rehang_tp_level(
                level,
                px,
                side=self.current_side,
                curr_px=px_now,
                consumed=consumed,
                live_qty=live_qty,
                initial_qty=float(self.initial_qty or live_qty),
                regime=int(self.regime or 3),
                tv_tps=list(self.tv_tps or []),
                regime_settings=self.regime_settings,
                open_tp_prices=open_prices,
                is_contracts=True,
                peak_px=float(getattr(self, "best_price", 0) or 0),
            )
            if skip and skip_reason in (
                "consumed", "price_book_filled", "qty_book_implies_filled", "price_past_tp",
            ):
                logger.warning(
                    f"  ⏭ 跳过补挂 TP{level} @ {px:.2f}（{skip_reason}·防死亡螺旋）"
                )
                if (
                    level
                    and level not in consumed
                    and skip_reason in ("price_book_filled", "qty_book_implies_filled", "price_past_tp")
                ):
                    consumed.add(level)
                    self.consumed_tp_levels = sorted(consumed)
                    if hasattr(self, "_save_state"):
                        self._save_state()
                    self._alert(
                        "warning",
                        "TP_SKIP_REHANG",
                        f"现价已过/已成交·拒绝补挂TP{level}",
                        f"原因={skip_reason} | 现价{px_now:.2f} | 实盘{live_qty}张",
                        {
                            "level": level,
                            "skip_reason": skip_reason,
                            "curr_px": px_now,
                            "live_qty": live_qty,
                            "consumed_tp_levels": sorted(consumed),
                            "exchange": "deepcoin",
                        },
                    )
                continue
            if skip and skip_reason == "no_mark_price":
                logger.warning(f"  ⏭ 无市价拒挂 TP{level}（防穿价秒成）")
                continue
            from app.core.tp_slice_guard import sanitize_tp_limit_price, tp_would_instant_fill
            if tp_would_instant_fill(self.current_side, px, px_now):
                if level and level not in consumed:
                    consumed.add(level)
                    self.consumed_tp_levels = sorted(consumed)
                    if hasattr(self, "_save_state"):
                        self._save_state()
                logger.warning(
                    f"  ⏭ 现价已过 TP{level} @ {px:.2f} mark={px_now:.2f}·禁止推离补挂"
                )
                continue
            place_px, adj = sanitize_tp_limit_price(self.current_side, px, px_now)
            if place_px <= 0 or adj.startswith("pushed"):
                if level and level not in consumed:
                    consumed.add(level)
                    self.consumed_tp_levels = sorted(consumed)
                    if hasattr(self, "_save_state"):
                        self._save_state()
                logger.warning(f"  ⏭ TP{level} 穿价拒绝补挂 {px:.2f} ({adj})")
                continue
            px = place_px
            orders = self._collect_tp_limit_orders()
            at_px = [o for o in orders if tp_price_matches(o["price"], px, price_tol)]
            if len(at_px) == 1 and tp_qty_matches(q, at_px[0]["qty"], live_qty, is_contracts=True):
                logger.info(f"  ✓ TP @ {px:.2f} 已存在 {at_px[0]['qty']}张，跳过")
                if hasattr(self, "_mark_tp_placed"):
                    self._mark_tp_placed(level, order_id=at_px[0].get("orderId"))
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
            placed_res = self._place_limit_with_retry(
                close_side, pos_side, q, px, label=f"TP{lv['level']}"
            )
            if placed_res.get("ok"):
                placed += 1
                if hasattr(self, "_mark_tp_placed"):
                    self._mark_tp_placed(int(lv.get("level") or 0), order_id=placed_res.get("order_id"))
            elif hasattr(self, "_alert"):
                self._alert(
                    "warning",
                    "TP_RETRY_FAIL",
                    f"TP{lv['level']}挂单重试失败",
                    f"TP @ {px} qty={q} 重试 {self.TP_RETRY_MAX} 次仍失败",
                    placed_res,
                )
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
        # After TP fills, avoid nuclear full-grid rehang (death spiral)
        consumed = self._consumed_tp_level_set()
        live_qty = float(audit.get("live_qty") or getattr(self, "watched_qty", 0) or 0)
        initial = float(getattr(self, "initial_qty", 0) or 0)
        if consumed or (initial > 0 and live_qty > 0 and live_qty < initial * 0.92):
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

    def _cancel_all_tp_limit_orders(self, *, flat_purge=False):
        cancelled = 0
        side_snap = self._flat_purge_side_snapshot() if flat_purge else None
        for o in self.client.get_pending_orders(self.symbol):
            is_tp = (
                self._is_flat_orphan_tp_order(o, side_snap)
                if flat_purge
                else self._is_tp_limit_order(o)
            )
            if not is_tp:
                continue
            oid = o.get("ordId")
            if oid:
                self.client.cancel_order(self.symbol, ord_id=oid)
                cancelled += 1
                time.sleep(0.15)
        if cancelled:
            label = "平仓孤儿止盈" if flat_purge else "限价止盈"
            logger.info(f"🧹 已撤销全部{label} {cancelled} 张")
        return cancelled

    def _cancel_tp_orders_at_levels(self, levels: list[int]) -> int:
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
                oid = o.get("ordId")
                if oid:
                    self.client.cancel_order(self.symbol, ord_id=oid)
                    cancelled += 1
                    time.sleep(0.15)
        return cancelled

    def _cancel_obsolete_tp_after_radar_move(self, radar_sl: float) -> dict:
        side = getattr(self, "current_side", None)
        obsolete = tp_levels_obsolete_by_radar(
            radar_sl,
            side,
            list(getattr(self, "tv_tps", []) or []),
            consumed_levels=list(getattr(self, "consumed_tp_levels", []) or []),
            max_level=3,
        )
        detail = format_obsolete_tp_detail(
            obsolete, radar_sl, list(getattr(self, "tv_tps", []) or []), side,
        )
        detail["cancelled"] = 0
        if not obsolete:
            return detail
        detail["cancelled"] = self._cancel_tp_orders_at_levels(obsolete)
        if detail["cancelled"] > 0:
            logger.info(
                f"🧹 雷达越过 TP{obsolete} → 撤销过时限价止盈 {detail['cancelled']} 张 @ SL {radar_sl:.2f}",
            )
            if hasattr(self, "_log"):
                self._log(
                    "TP_ORPHAN_PURGE",
                    f"呼吸止损 {radar_sl:.2f} 已越过 TP{obsolete}，撤销 {detail['cancelled']} 张",
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

    def _ensure_radar_sl(self, live_qty, sl_price):
        if not sl_price:
            return False
        curr_px = self._current_tp_price() if hasattr(self, "_current_tp_price") else 0.0
        latched = bool(getattr(self, "radar_latched", False))
        if (
            not latched
            and hasattr(self, "_radar_activation_reached")
            and not self._radar_activation_reached(curr_px)
        ):
            logger.info(
                "⏸️ 雷达未达激活条件（待档位路径比例或TP成交），跳过保本 STOP @ %.2f",
                float(sl_price),
            )
            return False
        sl = float(sl_price)
        if hasattr(self, "_clamp_radar_sl_to_tv_floor"):
            sl = self._clamp_radar_sl_to_tv_floor(sl)
        curr_px = self._current_tp_price()
        if curr_px > 0 and hasattr(self, "_mark_price_trusted") and self._mark_price_trusted(curr_px):
            if hasattr(self, "_market_safe_stop_price"):
                sl = self._market_safe_stop_price(sl, curr_px)
            else:
                sl = clamp_stop_market_safe(sl, curr_px, getattr(self, "current_side", None))
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
        """Restart: restore breathing stop (compat name kept for call sites)."""
        if hasattr(self, "_refresh_breathing_state_on_recover"):
            self._refresh_breathing_state_on_recover(curr_px, entry)
            return
        if curr_px <= 0 or not entry:
            return
        if self.best_price == 0.0:
            self.best_price = entry
        if self.current_side == "LONG":
            self.best_price = max(self.best_price, curr_px)
        else:
            self.best_price = min(self.best_price, curr_px)

    def _nuclear_realign_tp(self, live_qty, entry, dynamic_sl=None, rounds=3):
        """核武重挂：只撤 TP 限价，绝不 cancel_all（避免误撤呼吸止损条件槽）。"""
        curr_px = self._current_tp_price()
        last_audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
        for r in range(rounds):
            logger.warning(
                f"☢️ 核武级止盈清场重挂 {r + 1}/{rounds} | 持仓 {live_qty}张 | "
                f"当前 {last_audit['matched_full']}/{last_audit['expected']} | "
                f"{self._format_audit_summary(last_audit)}"
            )
            # Route A：TP123 ‖ 硬止损 ‖ 雷达 分槽；核武只动 TP 限价
            self._cancel_all_tp_limit_orders()
            time.sleep(1.0)
            placed = self._rebuild_defenses(live_qty, entry, dynamic_sl=None)
            logger.info(f"☢️ 核武轮 {r + 1} 新挂 {placed} 笔限价止盈")
            if dynamic_sl:
                time.sleep(0.6)
                self._ensure_radar_sl(live_qty, dynamic_sl)
            time.sleep(1.0)
            last_audit = self._audit_tp_levels(live_qty, curr_px=curr_px)
            ok_sl = bool(dynamic_sl)
            if self._defenses_fully_ok(
                live_qty, dynamic_sl, curr_px=curr_px, require_sl=ok_sl,
            ):
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
            # 核武只动 TP；雷达另槽事后补挂，禁止与硬止损抢份额
            audit = self._nuclear_realign_tp(live_qty, entry, dynamic_sl=None, rounds=3)
            matched = audit["matched_full"]
            pending_prices = audit["pending_prices"]
            rebuilt = nuclear = True
            if dynamic_sl and hasattr(self, "_ensure_radar_sl"):
                self._ensure_radar_sl(live_qty, dynamic_sl)

        return {
            "matched": matched,
            "expected": expected,
            "pending_prices": pending_prices,
            "rebuilt": rebuilt,
            "audit": audit,
            "nuclear": nuclear,
            "aligned": audit["matched_full"] >= expected and expected > 0,
            "summary": self._format_audit_summary(audit),
        }

    def _rebuild_defenses_after_tv_add(
        self,
        live_qty: float,
        entry: float,
        *,
        entry_type: str = "PYRAMID",
        prev_tv_tps: list | None = None,
    ) -> dict:
        """加仓后强制按新总头寸 + 最新 TV TP123 核武重挂，并同步 TV 止损/雷达。"""
        entry_type = str(entry_type or "PYRAMID").upper()
        reason = f"{entry_type} 加仓后按新总头寸重挂 TP123/雷达"
        logger.info(f"🧠 {reason}")
        curr_px = self._current_tp_price()
        side = getattr(self, "current_side", None)
        prev_sl = float(getattr(self, "tv_sl", 0) or 0)

        if hasattr(self, "_recompute_vps_hard_sl"):
            sl_meta = self._recompute_vps_hard_sl(entry_px=entry, side=side)
            if float(getattr(self, "tv_sl", 0) or 0) <= 0 and prev_sl > 0:
                self.tv_sl = prev_sl
                self._tv_stop_loss_ref = prev_sl
                self._pending_open_tv_sl = prev_sl
                sl_meta["restored_prev_tv_sl"] = prev_sl
                sl_meta["stop_price"] = prev_sl
                self._vps_hard_sl_meta = sl_meta
            logger.info(
                f"📐 加仓硬止损(TV): {float(getattr(self, 'tv_sl', 0) or 0):.2f} ({side})",
            )

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
            self._sync_consumed_tp_levels(live_qty, curr_px)
            self._cancel_all_tp_limit_orders()
            time.sleep(0.5)
            dynamic_sl = self._radar_sl_to_pass() if hasattr(self, "_radar_sl_to_pass") else None
            tp_result = self._nuclear_realign_tp(
                live_qty, entry, dynamic_sl=dynamic_sl, rounds=3,
            )
            dynamic_sl = self._radar_sl_to_pass() if hasattr(self, "_radar_sl_to_pass") else dynamic_sl
            if dynamic_sl and hasattr(self, "_realign_radar_defenses"):
                tp_result["radar_verified"] = bool(
                    self._realign_radar_defenses(live_qty, entry, dynamic_sl)
                )
            expected_slices = self._expected_tp_levels(live_qty, curr_px)

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
            exp = self._audit_live_exposure(
                live_qty, getattr(self, "current_side", None), curr_px=curr_px,
            )
            result["exposure"] = exp
            if exp.get("over_committed") and not exp.get("side_flip"):
                logger.warning(f"⚠️ 加仓后仍检测到止盈超挂: {exp.get('summary')}")
        return enrich_tp_alert_detail(result, regime=self.regime)

    def _place_limit_with_retry(
        self, close_side: str, pos_side: str, qty: float, price: float, label: str = "TP"
    ) -> dict:
        """Checklist §十: place failure → retry 3× then alert."""
        last_res = None
        last_err = None
        for attempt in range(1, self.TP_RETRY_MAX + 1):
            res = self.client.place_limit_order(
                self.symbol, close_side, pos_side, price, qty, reduce_only=True,
            )
            last_res = res
            if res and self.client._is_success(res):
                return {
                    "ok": True,
                    "label": label,
                    "res": res,
                    "attempt": attempt,
                    "qty": qty,
                    "price": price,
                }
            last_err = f"{label} attempt {attempt}/{self.TP_RETRY_MAX} failed"
            logger.warning(
                f"[User {self.user_id}] {last_err} qty={qty} price={price} res={res}"
            )
            if attempt < self.TP_RETRY_MAX:
                time.sleep(self.TP_RETRY_DELAY * attempt)
        return {
            "ok": False,
            "label": label,
            "res": last_res,
            "attempts": self.TP_RETRY_MAX,
            "error": last_err,
            "qty": qty,
            "price": price,
        }

    def _place_trigger_with_retry(
        self, close_side: str, pos_side: str, qty: float, trigger_price: float, label: str = "SL"
    ) -> dict:
        """Checklist §十: SL/trigger place failure → retry 3×."""
        last_res = None
        last_err = None
        for attempt in range(1, self.TP_RETRY_MAX + 1):
            res = self.client.place_trigger_order(
                self.symbol, close_side, pos_side, qty, trigger_price,
                order_type="market", td_mode="cross", mrg_position="merge",
            )
            last_res = res
            if res and self.client._is_success(res):
                return {
                    "ok": True,
                    "label": label,
                    "res": res,
                    "attempt": attempt,
                    "stop_price": trigger_price,
                }
            last_err = f"{label} attempt {attempt}/{self.TP_RETRY_MAX} failed"
            logger.warning(
                f"[User {self.user_id}] {last_err} stop={trigger_price} res={res}"
            )
            if attempt < self.TP_RETRY_MAX:
                time.sleep(self.TP_RETRY_DELAY * attempt)
        return {
            "ok": False,
            "label": label,
            "res": last_res,
            "attempts": self.TP_RETRY_MAX,
            "error": last_err,
            "stop_price": trigger_price,
        }

    def _place_radar_sl(self, live_qty, sl_price):
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"
        sl_qty = self._resolve_live_qty(live_qty)
        result = self._place_trigger_with_retry(
            close_side, pos_side, sl_qty, sl_price, label="RADAR_SL"
        )
        if not result.get("ok"):
            self._alert(
                "warning",
                "TP_RETRY_FAIL",
                "呼吸止损挂单重试失败",
                f"SL @ {sl_price} 重试 {self.TP_RETRY_MAX} 次仍失败",
                result,
            )
        return result


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
        if not ratios or len(ratios) < 3:
            # Guard against empty/partial regime ratios → IndexError
            return max(1, int(total_qty)), 0, 0

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
        blocked = self._block_if_trading_paused(raw_action) if hasattr(self, "_block_if_trading_paused") else None
        if blocked:
            return blocked

        # UPDATE_TP before mutating regime/atr/tv_sl — only replaces TP limits.
        if raw_action == "UPDATE_TP":
            if not self._lock.acquire(timeout=120.0):
                logger.error("⏱️ 锁等待 120s 超时，信号 UPDATE_TP 重新入队")
                self._signal_queue.put(payload)
                return
            try:
                self._record_tv_signal(payload, raw_action)
                return self._handle_update_tp(payload)
            finally:
                self._lock.release()

        held_regime = self.regime
        held_atr = self.current_atr
        prev_tv_tps = list(self.tv_tps)
        self._signal_prev_tv_tps = prev_tv_tps
        self.regime = clamp_regime(self._safe_int(payload.get("regime"), 3))

        # ATR/ADX from VPS market engine only — ignore webhook atr/adx
        self.risk_multiplier = float(payload.get("risk_multiplier", 1.0))
        position_open = bool(
            getattr(self, "monitoring", False)
            or float(getattr(self, "watched_qty", 0) or 0) > 0
        )
        if not position_open and hasattr(self, "_pull_vps_market_indicators"):
            self._pull_vps_market_indicators(force=True)
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
        if raw_action in ("LONG", "SHORT", "UPDATE_TP") or raw_action.startswith("CLOSE"):
            self._record_tv_signal(payload, raw_action)

        if not self._lock.acquire(timeout=120.0):
            logger.error(f"⏱️ 锁等待 120s 超时，信号 {raw_action} 重新入队")
            self._signal_queue.put(payload)
            return

        try:
            if is_tv_close_action(raw_action):
                skip, skip_reason = should_skip_tv_close_for_manual(self, raw_action)
                if skip:
                    return self._preserve_manual_on_tv_close(
                        raw_action, skip_reason=skip_reason, tv_reason=tv_reason,
                    )
                ignore, ignore_reason = should_ignore_bare_close_after_open(self, raw_action)
                if ignore:
                    logger.info("⏭️ %s", ignore_reason)
                    self._alert(
                        "info",
                        "CLOSE_DEFER",
                        "开仓保护期 · 忽略裸 CLOSE",
                        ignore_reason,
                        {"action": raw_action, "tv_reason": tv_reason, "regime": self.regime},
                    )
                    return

            self.monitoring = False
            # v6.5.6: reconcile-only closes — no market order (limits/radar already filled)
            from app.services.webhook_guard import (
                is_force_flat_close,
                is_reconcile_only_close,
            )
            if is_reconcile_only_close(raw_action):
                self._handle_tv_reconcile_close(raw_action, payload, tv_reason=tv_reason)
                return
            if is_force_flat_close(raw_action):
                self._close_all(
                    f"⚡ 策略反转全平：{tv_reason or raw_action}",
                    **_tv_close_kwargs(),
                )
                return
            if raw_action in ["LONG", "SHORT"]:
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

    def _handle_tv_reconcile_close(
        self, action: str, payload: dict | None = None, *, tv_reason: str | None = None,
    ) -> dict:
        """Checklist §2B: reconcile-only; NEVER market flatten."""
        payload = payload or {}
        leg = str(payload.get("leg") or "").strip()
        qty = float(payload.get("qty") or 0)
        price = float(payload.get("price") or 0)
        pos = self._get_active_position() if hasattr(self, "_get_active_position") else None
        live_qty = float(self._safe_qty((pos or {}).get("size", 0)) if hasattr(self, "_safe_qty") else (pos or {}).get("size") or 0)
        detail = {
            "type": "reconcile_only",
            "action": action,
            "leg": leg,
            "tv_qty": qty,
            "tv_price": price,
            "live_qty": live_qty,
            "tv_reason": tv_reason,
            "note": "TV对账信号·不下单（挂单/雷达已自行执行）",
        }
        if action == "CLOSE_TP" and leg in ("1", "2", "3"):
            try:
                lvl = int(leg)
                consumed = set(getattr(self, "consumed_tp_levels", None) or [])
                consumed.add(lvl)
                self.consumed_tp_levels = sorted(consumed)
            except (TypeError, ValueError):
                pass
            if live_qty > 0 and hasattr(self, "_bump_sl_after_tp_reconcile"):
                try:
                    detail["sl_bump"] = self._bump_sl_after_tp_reconcile(leg)
                except Exception as exc:
                    detail["sl_bump_error"] = str(exc)
            if hasattr(self, "_save_state"):
                self._save_state()
        if live_qty <= 0:
            if hasattr(self, "_purge_defense_orders_on_flat"):
                try:
                    self._purge_defense_orders_on_flat(reason=f"reconcile_{action}")
                except Exception:
                    pass
            if hasattr(self, "_clear_position_local_state"):
                try:
                    self._clear_position_local_state()
                except Exception:
                    pass
            elif hasattr(self, "_reset_adverse_radar"):
                try:
                    self._reset_adverse_radar(keep_tv_sl=False)
                except Exception:
                    pass
            detail["flat_confirmed"] = True
            detail["local_state_cleared"] = True
        self._log(action, f"TV对账 {action} leg={leg or '-'} live={live_qty}", detail)
        self._alert(
            "info",
            action,
            f"TV对账·{action}",
            f"leg={leg or '-'} qty={qty} price={price} 实盘={live_qty}（不下单）",
            detail,
        )
        return {"status": "ok", "action": action, "detail": detail}

    def _bump_sl_after_tp_reconcile(self, leg: str) -> dict:
        """After TP fill: update remaining_qty_pct and resize stop qty (no price bump).

        Aligned with PositionSupervisor — must call _boost_radar_after_tp_fill so
        DeepCoin TV-reconcile path also cancel/replace stop qty (70%/40%).
        """
        consumed = list(getattr(self, "consumed_tp_levels", None) or [])
        try:
            lvl = int(leg)
        except (TypeError, ValueError):
            lvl = 0
        if lvl in (1, 2, 3) and lvl not in consumed:
            consumed.append(lvl)
            self.consumed_tp_levels = sorted(set(consumed))
        if hasattr(self, "_remaining_qty_pct_from_consumed"):
            self.remaining_qty_pct = self._remaining_qty_pct_from_consumed(self.consumed_tp_levels)
        elif {1, 2, 3}.issubset(set(self.consumed_tp_levels)):
            self.remaining_qty_pct = 0.0
        elif {1, 2}.issubset(set(self.consumed_tp_levels)):
            self.remaining_qty_pct = 0.4
        elif 1 in self.consumed_tp_levels:
            self.remaining_qty_pct = 0.7
        else:
            self.remaining_qty_pct = 1.0
        change = {1: "tp1_filled", 2: "tp2_filled", 3: "tp3_filled"}.get(lvl)
        live_qty = float(getattr(self, "watched_qty", 0) or 0)
        if change and hasattr(self, "_boost_radar_after_tp_fill"):
            try:
                self._boost_radar_after_tp_fill(
                    change, float(getattr(self, "tv_price", 0) or 0), live_qty,
                )
            except Exception:
                pass
        elif hasattr(self, "_save_state"):
            self._save_state()
        return {
            "ok": True,
            "sl_bumped": False,
            "remaining_qty_pct": float(self.remaining_qty_pct),
            "leg": leg,
            "stop_resized": True,
            "note": "breathing stop: TP fill resizes stop qty only",
        }

    def _handle_manual_flat_detected(self, reason, *, skip_eager_purge=False):
        """人工全平 / 止盈吃满：立即撤 TP123 并智能复位账本"""
        logger.info(f"📭 感知空仓: {reason}")
        if not skip_eager_purge:
            self._purge_defense_orders_on_flat("manual_flat", notify=True)
        self.monitoring = False
        if hasattr(self, "_clear_position_local_state"):
            self._clear_position_local_state()
        else:
            self.watched_qty = 0
            self.watched_entry = 0.0
            self.initial_qty = 0
            self.base_qty = 0
            self.add_count = 0
            self.current_side = None
            self.best_price = 0.0
            self.current_sl = 0.0
            self.initial_stop = 0.0
            self.initial_atr = 0.0
            self.breakeven_phase = False
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
        if fields.get("leverage") is not None and int(fields["leverage"]) > 0:
            self.leverage = int(fields["leverage"])

    def _uses_tv_entry_routing(self) -> bool:
        return True

    def _resolve_entry_leverage(self) -> int:
        """v6.5.6: always 5x (TV leverage field deleted)."""
        from app.core.tv_entry_sizing import FIXED_LEVERAGE
        return int(FIXED_LEVERAGE)

    def _bind_tv_leverage(self) -> int:
        """Apply fixed 5x leverage before sizing/order."""
        lev = self._resolve_entry_leverage()
        self.leverage = lev
        client = getattr(self, "client", None)
        if client is not None:
            try:
                client.trading_leverage = lev
            except Exception:
                pass
            if hasattr(client, "set_leverage"):
                client.set_leverage(self.symbol, leverage=lev)
        return lev

    def _resolve_entry_qty(self, curr_px: float) -> tuple[int, dict]:
        """RISK20 sizing once at open → DeepCoin contracts (TV.qty distance-adjusted)."""
        from app.core.breathing_stop import compute_initial_stop

        equity = read_contract_equity(self.client)
        leverage = self._resolve_entry_leverage()
        tv_fields = getattr(self, "_tv_entry_fields", None) or {}
        tv_qty = tv_fields.get("tv_qty")
        price = float(curr_px or self.tv_price or 0)
        side = str(getattr(self, "_pending_open_side", None) or getattr(self, "current_side", None) or "").upper()
        if side not in ("LONG", "SHORT"):
            side = str(getattr(self, "last_tv_side", None) or "").upper()

        snap = {}
        if hasattr(self, "_pull_vps_market_indicators"):
            try:
                snap = self._pull_vps_market_indicators(force=True) or {}
            except Exception:
                snap = {}
        atr = float(snap.get("atr") or getattr(self, "current_atr", 0) or 0)
        atr_series = list(snap.get("atr_series") or [])
        tv_sl_ref = self._pine_stop_loss_ref() if hasattr(self, "_pine_stop_loss_ref") else float(
            getattr(self, "_tv_stop_loss_ref", 0)
            or getattr(self, "_pending_open_tv_sl", 0)
            or 0
        )
        from app.core.atr_emergency_fallback import (
            apply_fallback_atr,
            evaluate_emergency_atr_fallback,
        )
        from app.core.open_atr_guard import check_open_atr_or_reject

        fb = evaluate_emergency_atr_fallback(
            vps_atr=atr,
            atr_series=atr_series,
            entry=price,
            tv_stop_loss=tv_sl_ref if tv_sl_ref > 0 else None,
            mismatch_streak=int(getattr(self, "atr_mismatch_streak", 0) or 0),
        )
        self.atr_mismatch_streak = int(fb.get("mismatch_streak_next") or 0)
        atr_source = "vps"
        self._atr_fallback_pending_pause = False
        if fb.get("need_fallback"):
            fb_atr = apply_fallback_atr(fb)
            if fb_atr > 0:
                atr = fb_atr
                atr_source = "tv_emergency_fallback"
                self._atr_fallback_pending_pause = True
                self.atr_fallback_active = True
                self.current_atr = atr
                logger.error(
                    "⚠️ ATR应急降级·本笔使用TV隐含ATR=%.4f (VPS=%s reason=%s)",
                    atr, fb.get("vps_atr"), fb.get("reason"),
                )
                if hasattr(self, "_alert"):
                    self._alert(
                        "critical",
                        "ATR_FALLBACK",
                        "ATR应急降级·需人工确认后恢复",
                        (
                            f"原因={fb.get('reason')} | VPS ATR={fb.get('vps_atr')} | "
                            f"TV隐含ATR={fb.get('tv_implied_atr')} | "
                            f"Δ={fb.get('mismatch_pct')}% | 本笔已用降级ATR开仓；"
                            f"随后暂停本 symbol 自动开仓"
                        ),
                        dict(fb),
                    )
            else:
                atr_ok, atr_meta = check_open_atr_or_reject(
                    self,
                    atr=float(fb.get("vps_atr") or 0),
                    atr_series=atr_series,
                    side=side,
                    tv_sl_ref=tv_sl_ref if tv_sl_ref > 0 else None,
                )
                if not atr_ok:
                    atr_meta["atr_fallback"] = fb
                    return 0, atr_meta
        else:
            atr_ok, atr_meta = check_open_atr_or_reject(
                self,
                atr=atr,
                atr_series=atr_series,
                side=side,
                tv_sl_ref=tv_sl_ref if tv_sl_ref > 0 else None,
            )
            if not atr_ok:
                atr_meta["atr_fallback"] = fb
                return 0, atr_meta
            self.atr_fallback_active = False

        sizing_stop = 0.0
        if atr > 0 and price > 0 and side in ("LONG", "SHORT"):
            sizing_stop = float(compute_initial_stop(price, side, atr))

        qty, meta = resolve_vps_entry_qty_deepcoin(
            live_balance=equity,
            initial_principal=self.initial_principal,
            entry_type="OPEN",
            base_qty=float(getattr(self, "base_qty", 0) or 0),
            price=price,
            tv_sl=sizing_stop,
            tv_stop_loss=tv_sl_ref if tv_sl_ref > 0 else None,
            regime=int(self.regime or 3),
            exchange_leverage=leverage,
            face_value=self.face_value,
            symbol=self.canonical_symbol,
            tv_qty=float(tv_qty) if tv_qty else None,
        )
        meta["tv_sl_reference"] = tv_sl_ref if tv_sl_ref > 0 else None
        meta["sizing_stop"] = round(sizing_stop, 4) if sizing_stop else None
        meta["sizing_atr"] = round(atr, 4) if atr else None
        meta["sizing_side"] = side or None
        meta["atr_source"] = atr_source
        meta["atr_fallback"] = bool(atr_source == "tv_emergency_fallback")
        meta["atr_fallback_detail"] = fb
        if sizing_stop > 0:
            self._sizing_initial_stop = sizing_stop
            self.initial_atr = atr if atr > 0 else float(getattr(self, "initial_atr", 0) or 0)
        self._log(
            "SIGNAL",
            "📐 开仓算仓 "
            f"atr_src={atr_source} "
            f"adj={meta.get('adjust_coef')} "
            f"risk={meta.get('candidate_qty_by_risk')} "
            f"notional={meta.get('candidate_qty_by_notional')} "
            f"tv_adj={meta.get('candidate_qty_by_tv_adj')} "
            f"bind={meta.get('binding')} "
            f"final={meta.get('final_qty')}"
            + (f" err={meta.get('error')}" if meta.get("error") else ""),
        )
        if qty > 0:
            from app.core.combined_notional import check_combined_notional_cap

            notional = float(meta.get("notional_usd") or meta.get("position_value") or 0)
            if notional <= 0 and curr_px and self.face_value:
                notional = float(qty) * float(self.face_value) * float(curr_px)
            ok, cap_meta = check_combined_notional_cap(
                user_id=self.user_id,
                canonical=self.canonical_symbol,
                equity=equity if equity > 0 else self.initial_principal,
                new_notional=notional,
            )
            meta.update(cap_meta)
            if not ok:
                return 0, meta
        return qty, meta

    def _max_add_times(self) -> int:
        """妈妈版 pyramiding=1 — 加仓禁用."""
        return 0

    def _can_add_more(self) -> tuple[bool, str]:
        return False, "加仓已禁用（妈妈版单仓）"

    def _count_open_book_orders(self) -> int:
        from app.core.position_supervisor import PositionSupervisor

        return PositionSupervisor._count_open_book_orders(self)

    def _ensure_book_clean_before_open(self, reason: str = "pre_open") -> dict:
        from app.core.position_supervisor import PositionSupervisor

        return PositionSupervisor._ensure_book_clean_before_open(self, reason)

    def _force_flat_before_open(self, reason: str) -> bool:
        from app.core.position_supervisor import PositionSupervisor

        return PositionSupervisor._force_flat_before_open(self, reason)

    def _handle_tv_entry(self, action, curr_px, *, has_pos, current_side):
        """妈妈版：LONG/SHORT 一律先平后开，永不加仓。"""
        logger.info(f"⚡ TV OPEN [{action}] 铁律·先平后开（妈妈版单仓·无加仓）")
        if not self._force_flat_before_open(f"TV OPEN [{action}] 铁律·先平后开"):
            return
        self._open_position(action, curr_px)

    def _add_to_position(self, action, curr_px, entry_type):
        """Disabled — redirect to flatten+open."""
        logger.info(f"⏭️ {entry_type} 加仓已禁用 → 降级先平后开")
        if not self._force_flat_before_open(f"{entry_type}禁用·先平后开"):
            return
        self._open_position(action, curr_px)

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
        """遗留同向换仓入口 → 统一走铁律先平后开。"""
        threshold = float(settings.SAME_DIR_IGNORE_PRICE_DIFF_PCT)
        reason = format_reopen_reason(ev, threshold)
        logger.info(f"⚡ 收到建仓信号 [{action}]，{reason} → 铁律先平后开")
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
        if not self._force_flat_before_open(f"SAME_DIR_REOPEN·{reason}"):
            logger.error("同向换仓平仓后仍未归零，暂缓新开仓")
            return
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
            vps_meta = getattr(self, "_vps_hard_sl_meta", None) or {}
            if vps_meta.get("hard_sl_pct_display"):
                detail["hard_sl_pct_display"] = vps_meta["hard_sl_pct_display"]
            if vps_meta.get("tv_sl_reference"):
                detail["tv_sl_reference"] = vps_meta["tv_sl_reference"]
        self._save_state()

    def _place_tv_entry_order(self, action: str, qty: float, limit_px: float) -> dict:
        """Checklist §2A: 市价开仓."""
        open_side = "buy" if action == "LONG" else "sell"
        pos_side = "long" if action == "LONG" else "short"
        meta: dict = {
            "entry_order_style": "market",
            "limit_price": float(limit_px or 0),
            "qty": float(qty),
        }
        self.client.place_market_order(self.symbol, open_side, pos_side, qty)
        return meta

    def _open_position(self, action, curr_px):
        if hasattr(self, "_clear_trading_pause"):
            self._clear_trading_pause("new_open")
        leverage = self._bind_tv_leverage()
        self.client.cancel_all_open_orders(self.symbol)
        time.sleep(0.4)
        if float(getattr(self, "tv_sl", 0) or 0) <= 0:
            recovered = float(
                getattr(self, "_tv_stop_loss_ref", 0)
                or getattr(self, "_pending_open_tv_sl", 0)
                or 0
            )
            if recovered > 0:
                self.tv_sl = recovered
                self._tv_stop_loss_ref = recovered
                self._pending_open_tv_sl = recovered
                logger.info(f"开仓前恢复 TV stop_loss ref@{recovered:.4f}")
        qty, sizing_meta = self._resolve_entry_qty(curr_px)
        if qty <= 0:
            err = sizing_meta.get("error", "insufficient_balance")
            alert_type = (
                "NOTIONAL_CAP"
                if err in ("combined_notional_exceeded", "total_nominal_exceeded")
                else "INSUFFICIENT_BALANCE"
            )
            title = "总名义敞口超限" if alert_type == "NOTIONAL_CAP" else "开仓失败"
            logger.error(f"开仓失败: {err} | {sizing_meta}")
            self._alert(
                "warning",
                alert_type,
                title,
                f"用户 {self.user_id} {getattr(self, 'canonical_symbol', '')}: {err} | "
                f"名义={sizing_meta.get('proposed_notional') or sizing_meta.get('order_amount')} "
                f"上限={sizing_meta.get('notional_cap')} ({sizing_meta.get('max_mult')}×本金)",
                {
                    **sizing_meta,
                    "symbol": getattr(self, "canonical_symbol", None),
                    "max_combined_mult": sizing_meta.get("max_mult"),
                },
            )
            return {"status": "error", "reason": err, "message": f"无法开仓（{err}）"}
        open_side = "buy" if action == "LONG" else "sell"
        entry_type = getattr(self, "_entry_type", "OPEN")
        limit_px = float(getattr(self, "tv_price", 0) or curr_px or 0)

        logger.info(
            f"🚀 [VPS开仓] {open_side} {qty} 张 | {entry_type} R{self.regime} | "
            f"LIMIT@{limit_px:.4f}→市价补 | "
            f"名义{sizing_meta.get('order_amount')}U / sl_dist={sizing_meta.get('sl_distance')} "
            f"| TV杠杆{leverage}×"
        )
        self._last_open_sizing_meta = dict(sizing_meta or {})
        self._last_open_sizing_meta["leverage"] = leverage
        entry_meta = self._place_tv_entry_order(action, qty, limit_px)
        self._last_open_sizing_meta["entry_order"] = entry_meta
        time.sleep(1.2)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self.current_side = action
            real_qty = self._safe_qty(pos['size'])
            entry_price = float(pos.get('entry_price', 0) or 0)
            # 开仓宽限：禁止立刻 CAP 市价减仓
            self.trade_opened_at = time.time()
            self.base_qty = real_qty
            self.initial_qty = real_qty
            self.add_count = 0
            self.consumed_tp_levels = []
            self._tp_fill_dingtalk_levels = set()
            self.current_trade_id = self.on_trade_open(
                self.user_id, action, real_qty, entry_price or float(pos.get("entry_price", 0) or 0),
                self.regime, self.tv_tps,
                symbol=self.canonical_symbol,
            )
            self.adopted_manual = False
            protect = self._protect_and_monitor(real_qty, entry_price or pos['entry_price'])
            if isinstance(protect, dict) and protect.get("aborted"):
                logger.error("开仓后硬止损失败已撤仓·跳过OPEN钉钉")
                return {"status": "error", "reason": "hard_sl_fail_abort", "detail": protect}
            if getattr(self, "_atr_fallback_pending_pause", False):
                self._atr_fallback_pending_pause = False
                if hasattr(self, "_pause_trading"):
                    self._pause_trading(
                        "ATR应急降级后暂停·待人工确认VPS ATR恢复",
                        {
                            "atr_source": sizing_meta.get("atr_source"),
                            "atr_fallback_detail": sizing_meta.get("atr_fallback_detail"),
                            "trade_id": self.current_trade_id,
                            "tag": "atr_emergency_fallback",
                        },
                    )
            return {"status": "ok", "action": action, "trade_id": self.current_trade_id}

    def _protect_and_monitor(self, qty, entry_price):
        """
        开仓后一次性挂好 TP123 + 呼吸止损；实盘核实后才推钉钉。
        返回 {ok, aborted, defense, shield}。
        """
        self._reset_adverse_radar(keep_tv_sl=False)
        self._init_breathing_on_open(
            entry_price,
            atr=float(getattr(self, "current_atr", 0) or getattr(self, "initial_atr", 0) or 0),
            adx=float(getattr(self, "current_adx", 0) or 0) or None,
        )
        tp_pxs = self.tv_tps
        self.best_price = entry_price
        self.watched_qty, self.watched_entry, self.monitoring = qty, entry_price, True
        self._save_state()

        self._ensure_price_ws()

        result: dict = {}
        shield: dict = {}
        verified = self._wait_verify(lambda: self._verify_position(self.current_side))
        if verified:
            live_qty = self._safe_qty(verified["size"])
            entry = verified["entry_price"]
            # ① 只挂 TP123
            result = self._smart_realign_defenses(
                live_qty, entry,
                dynamic_sl=None,
                reason="开仓后智能防线对齐·仅TP123",
            )
            if (
                result.get("expected", 0) > 0
                and result.get("matched", 0) < result.get("expected", 0)
            ):
                logger.warning(
                    f"开仓TP未齐 {result.get('matched')}/{result.get('expected')} → 再核武一轮"
                )
                audit = self._nuclear_realign_tp(live_qty, entry, dynamic_sl=None, rounds=2)
                result = {
                    **result,
                    "matched": audit.get("matched_full", result.get("matched")),
                    "expected": audit.get("expected", result.get("expected")),
                    "audit": audit,
                    "nuclear_retry": True,
                }
            self._last_defense_result = result
            matched, expected = result.get("matched", 0), result.get("expected", 0)
            audit = result.get("audit") or {}
            if expected > 0 and matched < expected:
                self._dt.report_system_alert(
                    "开仓后限价止盈未全部挂上",
                    f"{self.current_side} {verified['size']}张 | 仅 {matched}/{expected} 档 | "
                    f"{self._format_audit_summary(audit)}",
                )
            # ② 呼吸止损只挂一次
            shield = self._sync_tv_hard_stop(live_qty, at_open=True, force_replace=True)
            self._last_shield_result = shield
            armed = bool(
                shield.get("placed", 0) > 0
                or shield.get("armed")
                or shield.get("aligned")
                or shield.get("skipped") == "live_already_aligned"
            )
            sl_label = shield.get("label") or self._hard_stop_label()
            breath_sl = float(
                getattr(self, "current_sl", 0)
                or getattr(self, "initial_stop", 0)
                or getattr(self, "tv_sl", 0)
                or 0
            )
            if armed:
                logger.info(
                    f"🛡️ 开仓 {sl_label}已挂 @{shield.get('stop_price', 0):.2f} | "
                    f"{verified['size']}张"
                )
            elif breath_sl > 0:
                self._dt.report_system_alert(
                    "开仓后硬止损未挂上·立即撤仓",
                    f"{self.current_side} {verified['size']}张 | "
                    f"breath_sl={breath_sl} | {shield}",
                )
                try:
                    self._close_all(
                        "硬止损挂单失败·禁止裸奔",
                        close_action="HARD_SL_FAIL_ABORT",
                        close_trigger="hard_sl_place_failed",
                    )
                except Exception as e:
                    logger.error(f"hard-SL fail abort close error: {e}")
                self.monitoring = False
                out = {
                    "ok": False,
                    "aborted": True,
                    "reason": "hard_sl_fail_abort",
                    "defense": result,
                    "shield": shield,
                }
                self._last_protect_result = out
                return out

            # ③ 实盘核实（TP + 呼吸止损）后才推 OPEN 钉钉一次
            verify_note = (
                f"持仓 {verified['size']}张 @ {verified['entry_price']:.2f} | "
                f"限价止盈 {matched}/{expected} 档 | {self._format_audit_summary(audit)}"
            )
            if armed:
                verify_note += f" | {sl_label}已核实 @{shield.get('stop_price', 0):.2f}"
            self._record_open_log(
                self.current_side, live_qty, entry, source="open",
            )
            self._dt.report_supervisor_open(
                self.current_side, verified['entry_price'], self.tv_price,
                verified['size'], tp_pxs, self.current_atr, self.regime, self.tv_tps,
                verify_note=verify_note,
                tp_audit=audit,
                shield=shield,
                tv_sl=float(getattr(self, "tv_sl", 0) or 0),
                initial_stop=float(getattr(self, "initial_stop", 0) or 0),
                initial_atr=float(getattr(self, "initial_atr", 0) or 0),
                current_adx=float(getattr(self, "current_adx", 0) or 0),
                radar_armed=True,
                radar_active=True,
                radar_standby=False,
                hard_sl_mounted=bool(armed),
                tp123_mounted=bool(expected > 0 and matched >= expected) or (expected == 0),
                mount_confirm={
                    "hard_sl": "✅" if armed else "❌",
                    "tp123": "✅" if (expected == 0 or matched >= expected) else "❌",
                    "radar": "✅",
                },
                leverage=int(getattr(self, "leverage", 0) or 0),
                **(getattr(self, "_last_open_sizing_meta", None) or {}),
                **enrich_tp_alert_detail({}, regime=self.regime),
            )
        else:
            logger.warning("开仓钉钉跳过：实盘持仓核查未通过")
            out = {
                "ok": False,
                "aborted": False,
                "reason": "position_verify_failed",
                "defense": result,
                "shield": shield,
            }
            self._last_protect_result = out
            threading.Thread(target=self._sentinel_loop, daemon=True).start()
            return out

        threading.Thread(target=self._sentinel_loop, daemon=True).start()
        out = {
            "ok": True,
            "aborted": False,
            "defense": result,
            "shield": shield,
            "radar_standby": False,
            "breathing_active": True,
        }
        self._last_protect_result = out
        return out

    def _ensure_price_ws(self):
        """Keep markPrice WS alive and bind radar to every tick (fastest path)."""
        if hasattr(self.client, "start_public_price_ws"):
            self.client.start_public_price_ws(self.symbol)
        if hasattr(self.client, "register_price_listener") and not self._radar_ws_bound:
            self.client.register_price_listener(self._on_ws_price_tick)
            self._radar_ws_bound = True

    def _unbind_price_ws_listener(self):
        if self._radar_ws_bound and hasattr(self.client, "unregister_price_listener"):
            try:
                self.client.unregister_price_listener(self._on_ws_price_tick)
            except Exception:
                pass
        self._radar_ws_bound = False

    def _on_ws_price_tick(self, symbol, price):
        """WebSocket mark push → immediate TP1-path / trail evaluate (throttled)."""
        if not self.monitoring or float(price or 0) <= 0:
            return
        want = str(getattr(self, "symbol", "") or "").upper()
        got = str(symbol or "").upper()
        if want and got and want != got:
            a = want.replace("-", "").replace("_", "").replace("SWAP", "")
            b = got.replace("-", "").replace("_", "").replace("SWAP", "")
            if a != b and not (a.startswith(b[:6]) or b.startswith(a[:6])):
                return
        now = time.time()
        if now - float(getattr(self, "_radar_ws_tick_ts", 0) or 0) < RADAR_WS_TICK_MIN_SEC:
            return
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._radar_ws_tick_ts = now
            self._radar_ws_fast_tick(float(price))
        except Exception as exc:
            logger.debug("[User %s] WS radar tick: %s", self.user_id, exc)
        finally:
            self._lock.release()

    def _radar_ws_fast_tick(self, curr_px):
        """WS-driven radar: sync TP fills + arm/trail on remaining qty."""
        if curr_px <= 0 or not self.monitoring:
            return
        pos = self._get_active_position()
        if not pos or self._safe_qty(pos.get("size")) <= 0:
            return
        live_qty = self._safe_qty(pos["size"])
        entry = float(pos.get("entry_price") or self.watched_entry or 0)
        if self.current_side == "LONG":
            self.best_price = max(float(self.best_price or entry or 0), curr_px)
        elif self.current_side == "SHORT":
            bp = float(self.best_price or entry or 0)
            self.best_price = min(bp, curr_px) if bp > 0 else curr_px
        before = set(int(x) for x in (self.consumed_tp_levels or []))
        self._sync_consumed_tp_levels(live_qty, curr_px)
        after = set(int(x) for x in (self.consumed_tp_levels or []))
        gained = sorted(after - before)
        if gained:
            from app.core.position_supervisor import PositionSupervisor
            PositionSupervisor._notify_tp_fill_detected(
                self, gained[0], self.watched_qty or live_qty, live_qty, curr_px,
            )
            if hasattr(self, "_boost_radar_after_tp_fill"):
                self._boost_radar_after_tp_fill(f"tp{gained[0]}_filled", curr_px, live_qty)
        self.watched_qty = live_qty
        if entry > 0:
            self.watched_entry = entry
        self._orchestrate_defense_monitoring(live_qty, curr_px)

    def _radar_activation_progress(self, curr_px):
        if curr_px <= 0 or not self.watched_entry:
            return 0.0
        tp1 = float(self.tv_tps[0] or 0) if self.tv_tps else 0.0
        if tp1 > 0:
            return tp_path_progress(self.watched_entry, curr_px, tp1, self.current_side)
        return 0.0

    def _sentinel_poll_sec(self, curr_px=0.0):
        """WS-aligned cadence: arming/trail ~1s; far from TP1 slightly slower."""
        if hasattr(self, "_is_radar_engaged") and self._is_radar_engaged():
            return SENTINEL_POLL_RADAR
        if self._is_radar_active():
            return SENTINEL_POLL_RADAR
        if tp1_filled_from_consumed(getattr(self, "consumed_tp_levels", None)):
            return SENTINEL_POLL_RADAR
        if curr_px > 0 and self.watched_entry and self.tv_tps:
            progress = self._radar_activation_progress(curr_px)
            act = 0.70
            if hasattr(self, "_regime_radar_activation"):
                act = float(self._regime_radar_activation() or 0.70)
            else:
                row = (self.regime_settings.get(self.regime) or {})
                act = float(row.get("activation") or 0.70)
            if progress + 1e-9 >= max(0.40, act * 0.55):
                return SENTINEL_POLL_ARMING
        return SENTINEL_POLL_NORMAL

    def _process_radar_trailing(self, real_amt, curr_px):
        # Same as Binance: only timeout-cancel when mark already past TP; refresh stamp otherwise.
        try:
            from app.core.tp_slice_guard import tp_would_instant_fill
            from app.core.vps_radar_stages import TP_LIMIT_TIMEOUT_SEC
            now = time.time()
            placed = dict(getattr(self, "_tp_placed_at", None) or {})
            for lvl, ts in list(placed.items()):
                if now - float(ts) < TP_LIMIT_TIMEOUT_SEC:
                    continue
                if int(lvl) in (getattr(self, "consumed_tp_levels", None) or []):
                    placed.pop(lvl, None)
                    self._tp_placed_at = placed
                    continue
                try:
                    idx = int(lvl) - 1
                    tp_px = float((self.tv_tps or [0, 0, 0])[idx] or 0) if idx >= 0 else 0.0
                except (TypeError, ValueError, IndexError):
                    tp_px = 0.0
                if tp_px > 0 and float(curr_px or 0) > 0 and not tp_would_instant_fill(
                    self.current_side, tp_px, float(curr_px or 0),
                ):
                    placed[lvl] = now
                    self._tp_placed_at = placed
                    self._save_state()
                    continue
                try:
                    cancelled = 0
                    if hasattr(self, "_cancel_tp_orders_at_levels"):
                        cancelled = int(self._cancel_tp_orders_at_levels([int(lvl)]) or 0)
                    consumed = set(getattr(self, "consumed_tp_levels", None) or [])
                    consumed.add(int(lvl))
                    self.consumed_tp_levels = sorted(consumed)
                    placed.pop(lvl, None)
                    self._tp_placed_at = placed
                    self._save_state()
                    self._alert(
                        "warning", "TP_SKIP_REHANG", "TP挂单超时·移交呼吸止损",
                        f"TP{lvl} 超过{int(TP_LIMIT_TIMEOUT_SEC)}s且现价已过"
                        f"（撤单{cancelled}）·禁止重挂",
                        {
                            "level": int(lvl),
                            "cancelled": cancelled,
                            "exchange": "deepcoin",
                            "timeout_not_fill": True,
                            "mark_past_tp": True,
                        },
                    )
                except Exception:
                    pass
        except Exception:
            pass

        if hasattr(self, "_process_breathing_stop_tick"):
            return bool(self._process_breathing_stop_tick(real_amt, curr_px))
        return False

    def _sentinel_loop(self):
        """哨兵：持仓/TP 防线 + 雷达移动保本（WS tick 为主，REST 自适应轮询兜底）"""
        last_px = 0.0
        while self.monitoring:
            try:
                self._ensure_price_ws()
                if not self._lock.acquire(timeout=2.0):
                    continue
                try:
                    from app.core.exchange_errors import ExchangeTransientError
                    try:
                        pos = self._get_active_position()
                    except ExchangeTransientError:
                        continue
                    real_amt = self._safe_qty(pos.get("size")) if pos else 0
                    actual_side = "LONG" if pos and pos.get('posSide') == "long" else "SHORT"

                    if real_amt == 0:
                        if self.watched_qty > 0:
                            self._purge_defense_orders_on_flat(
                                "sentinel_zero_eager", notify=False,
                            )
                            self._handle_manual_flat_detected(
                                "仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)",
                                skip_eager_purge=True,
                            )
                        break

                    if self.watched_qty > 0 and self._should_finalize_tp_victory(real_amt):
                        self._sweep_dust_and_finalize(
                            "仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)"
                        )
                        break

                    if self._sentinel_force_align_if_opposite(actual_side):
                        break

                    entry_px = float(pos.get("entry_price", 0) or self.watched_entry or 0) if pos else 0.0
                    curr_px = self.client.get_current_price(self.symbol, prefer_ws=True)
                    if curr_px <= 0:
                        curr_px = last_px
                    else:
                        last_px = curr_px

                    exposure = self._audit_live_exposure(
                        real_amt, actual_side, curr_px=curr_px,
                    )
                    if exposure.get("side_flip"):
                        self._remediate_exposure_anomaly(
                            exposure, entry_px, trigger="sentinel_side_flip", curr_px=curr_px,
                        )
                        break
                    if exposure.get("over_committed"):
                        self._remediate_exposure_anomaly(
                            exposure, entry_px, trigger="sentinel_tp_over_commit", curr_px=curr_px,
                        )

                    if not self.last_tv_side:
                        self.last_tv_side = actual_side
                        self._save_state()

                    cap_px = curr_px or entry_px
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
                    booked_side = resolve_booked_side(
                        current_side=self.current_side,
                        last_tv_side=self.last_tv_side,
                    )
                    if qty_changed and booked_side and actual_side != booked_side:
                        exposure_flip = self._audit_live_exposure(
                            real_amt, actual_side, curr_px=curr_px,
                        )
                        self._remediate_exposure_anomaly(
                            exposure_flip, entry_px, trigger="sentinel_qty_flip", curr_px=curr_px,
                        )
                        break
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
                    curr_px = self.client.get_current_price(self.symbol, prefer_ws=True)
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
                    before_c = set(int(x) for x in (self.consumed_tp_levels or []))
                    self._sync_consumed_tp_levels(real_amt, curr_px)
                    after_c = set(int(x) for x in (self.consumed_tp_levels or []))
                    gained_c = sorted(after_c - before_c)
                    if gained_c:
                        from app.core.position_supervisor import PositionSupervisor
                        PositionSupervisor._notify_tp_fill_detected(
                            self, gained_c[0], self.watched_qty, real_amt, curr_px,
                        )

                    if not qty_changed and self._scan_ticks % 10 == 0:
                        audit = self._audit_tp_levels(real_amt, curr_px=curr_px)
                        if audit["issues"]:
                            logger.info(
                                f"🔍 定期扫描发现异常: {audit['issues']}，触发智能补挂"
                            )
                            sl_to_pass = self._radar_sl_to_pass()
                            # TP 补挂不带雷达 SL，避免与条件止损抢份额
                            self._smart_realign_defenses(
                                real_amt, self.watched_entry, dynamic_sl=None,
                                reason="定期防线扫描·仅TP限价·不碰雷达硬止损",
                            )
                            if sl_to_pass and hasattr(self, "_ensure_radar_sl"):
                                self._ensure_radar_sl(real_amt, sl_to_pass)

                    progress = self._radar_activation_progress(curr_px)
                    self._orchestrate_defense_monitoring(real_amt, curr_px)
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
        # Dedupe first — never stack another layer on existing duplicates
        if self._has_duplicate_tp_orders():
            purged = self._purge_duplicate_tp_orders(live_qty)
            if purged:
                logger.warning(f"🧹 重建前去重撤销 {purged} 张多余止盈")
                time.sleep(0.35)
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
            level = int(lv.get("level") or 0)
            if q <= 0 or px <= 0:
                continue
            from app.core.tp_slice_guard import should_skip_rehang_tp_level, tp_would_instant_fill
            open_prices = [float(o.get("price", 0) or 0) for o in self._collect_tp_limit_orders()]
            consumed_now = self._consumed_tp_level_set()
            skip, skip_reason = should_skip_rehang_tp_level(
                level,
                px,
                side=self.current_side,
                curr_px=curr_px,
                consumed=consumed_now,
                live_qty=live_qty,
                initial_qty=float(self.initial_qty or live_qty),
                regime=int(self.regime or 3),
                tv_tps=list(self.tv_tps or []),
                regime_settings=self.regime_settings,
                open_tp_prices=open_prices,
                is_contracts=True,
                peak_px=float(getattr(self, "best_price", 0) or 0),
            )
            if skip or tp_would_instant_fill(self.current_side, px, curr_px):
                logger.warning(
                    f"  ⏭ 重建跳过 TP{level} @ {px:.2f}（{skip_reason or 'mark_past'}）"
                )
                if level and level not in consumed_now:
                    consumed_now.add(level)
                    self.consumed_tp_levels = sorted(consumed_now)
                    if hasattr(self, "_save_state"):
                        self._save_state()
                continue
            # Same existence check as _patch_missing_tp_levels / Binance _rebuild_tp_limit_orders
            orders = self._collect_tp_limit_orders()
            at_px = [o for o in orders if tp_price_matches(o["price"], px)]
            if len(at_px) == 1 and tp_qty_matches(q, at_px[0]["qty"], live_qty, is_contracts=True):
                logger.info(f"  ✓ TP{level} @ {px:.2f} 已存在 {at_px[0]['qty']}张，跳过（防重复挂单）")
                if hasattr(self, "_mark_tp_placed"):
                    self._mark_tp_placed(level, order_id=at_px[0].get("orderId"))
                continue
            if len(at_px) > 1:
                self._purge_duplicate_tp_orders(live_qty)
                orders = self._collect_tp_limit_orders()
                at_px = [o for o in orders if tp_price_matches(o["price"], px)]
                if len(at_px) == 1 and tp_qty_matches(q, at_px[0]["qty"], live_qty, is_contracts=True):
                    continue
            for o in at_px:
                if o.get("orderId"):
                    self.client.cancel_order(self.symbol, ord_id=o["orderId"])
                    time.sleep(0.25)
            placed_res = self._place_limit_with_retry(
                close_side, pos_side, q, px, label=f"TP{level}"
            )
            if placed_res.get("ok"):
                placed += 1
                if hasattr(self, "_mark_tp_placed"):
                    self._mark_tp_placed(level, order_id=placed_res.get("order_id"))
            elif hasattr(self, "_alert"):
                self._alert(
                    "warning",
                    "TP_RETRY_FAIL",
                    f"TP{level}挂单重试失败",
                    f"TP @ {px} qty={q} 重试 {self.TP_RETRY_MAX} 次仍失败",
                    placed_res,
                )
            time.sleep(0.35)

        if dynamic_sl:
            sl_qty = self._resolve_live_qty(live_qty)
            sl_res = self._place_trigger_with_retry(
                close_side, pos_side, sl_qty, dynamic_sl, label="SL"
            )
            if sl_res.get("ok") and hasattr(self, "_remember_defense_order_id"):
                self._remember_defense_order_id("sl", sl_res.get("order_id") or sl_res.get("algo_id"))
            if not sl_res.get("ok") and hasattr(self, "_alert"):
                self._alert(
                    "warning",
                    "TP_RETRY_FAIL",
                    "止损挂单重试失败",
                    f"SL @ {dynamic_sl} 重试 {self.TP_RETRY_MAX} 次仍失败",
                    sl_res,
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
        close_trigger: str | None = None,
        attribution: dict | None = None,
    ):
        """三重把关之二：TV 全平/保护性全平 → 先撤单释放冻结仓位，6 轮阶梯强平至归零"""
        _ = close_trigger, attribution  # accepted for mixin / Binance signature parity
        entry_snapshot = float(self.watched_entry or 0)
        qty_snapshot = float(self.watched_qty or 0)
        side_snapshot = self.current_side
        trade_id_snapshot = self.current_trade_id
        self._purge_defense_orders_on_flat("code_close_all", notify=False)
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
        self._unbind_price_ws_listener()
        self._disarm_adverse_staged_stops(reason="flat_reset", notify=False)
        if hasattr(self, "_clear_position_local_state"):
            self._clear_position_local_state()
        else:
            self._reset_adverse_radar(keep_tv_sl=False)
            self.watched_qty = 0
            self.watched_entry = 0.0
            self.initial_qty = 0
            self.base_qty = 0
            self.add_count = 0
            self.current_side = None
            self.best_price = 0.0
        self._save_state()
        self._purge_defense_orders_on_flat("flat_reset", notify=True)

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
                    self.initial_atr = float(s.get("initial_atr", 0) or 0)
                    self.initial_stop = float(s.get("initial_stop", 0) or 0)
                    self.breakeven_phase = bool(s.get("breakeven_phase", False))
                    self.current_adx = float(s.get("current_adx", 25) or 25)
                    self.remaining_qty_pct = float(s.get("remaining_qty_pct", 1.0) or 1.0)
                    # Old radar schema detection (activated/stepCount without breathing fields)
                    has_old = (
                        ("radar_activated" in s or "radar_step_count" in s or "step_count" in s)
                        and float(s.get("initial_atr", 0) or 0) <= 0
                    )
                    self._state_schema_legacy = bool(has_old) or int(s.get("schema_version") or 0) < 2
                    self.tv_tps = self._sanitize_tp_prices(s.get("tv_tps", [0.0, 0.0, 0.0]))
                    self.tv_price = float(s.get("tv_price", 0.0) or 0.0)
                    self.best_price = s.get("best_price", 0.0)
                    self.watched_qty = s.get("watched_qty", 0)
                    self.watched_entry = s.get("watched_entry", 0.0)
                    self.initial_qty = s.get("initial_qty", 0)
                    self.base_qty = float(s.get("base_qty", 0) or s.get("initial_qty", 0) or 0)
                    self.add_count = 0
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
                    self._tv_stop_loss_ref = float(
                        s.get("tv_stop_loss_ref") or s.get("tv_sl", 0) or 0
                    )
                    self._tv_hard_sl_price = float(
                        s.get("tv_hard_sl_price")
                        or s.get("current_sl", 0)
                        or 0
                    )
                    if self._tv_hard_sl_price <= 0 and float(s.get("initial_stop", 0) or 0) > 0:
                        self._tv_hard_sl_price = float(s.get("initial_stop") or 0)
                    lev = int(s.get("leverage", 0) or 0)
                    if lev > 0:
                        self.leverage = lev
                    saved_fields = s.get("tv_entry_fields")
                    if isinstance(saved_fields, dict) and saved_fields:
                        self._tv_entry_fields = dict(saved_fields)
                    self.adopted_manual = bool(s.get("adopted_manual", False))
                    self.radar_latched = bool(s.get("radar_latched", False))
                    self.radar_activated = bool(s.get("radar_activated", False) or s.get("radar_latched", False))
                    self.radar_step_count = max(int(s.get("radar_step_count", 0) or 0), 0)
                    raw_tp_at = s.get("tp_placed_at") or {}
                    self._tp_placed_at = (
                        {int(k): float(v) for k, v in dict(raw_tp_at).items()}
                        if isinstance(raw_tp_at, dict) else {}
                    )
                    raw_oids = s.get("defense_order_ids") or {}
                    if isinstance(raw_oids, dict):
                        cleaned = {}
                        for k, v in raw_oids.items():
                            key = str(k).strip().lower()
                            if key.startswith("tp"):
                                key = key[2:]
                            if key not in ("1", "2", "3", "sl") or v in (None, ""):
                                continue
                            try:
                                cleaned[key] = int(v)
                            except (TypeError, ValueError):
                                cleaned[key] = str(v)
                        self._defense_order_ids = cleaned
                    else:
                        self._defense_order_ids = {}
                    self.trading_paused = bool(s.get("trading_paused", False))
                    self.trading_pause_reason = str(s.get("trading_pause_reason") or "")
                    tid = s.get("current_trade_id")
                    if tid is not None:
                        try:
                            self.current_trade_id = int(tid)
                        except (TypeError, ValueError):
                            pass
                    self._infer_radar_latched_from_state()

            if self._scan_and_sweep_dust_on_startup():
                return

            if self._recover_missed_flat_on_startup(was_monitoring=saved_monitoring):
                return

            pos = self._get_active_position()
            if pos and self._safe_qty(pos.get("size", 0)) != 0:
                saved_state_tv_side = self.last_tv_side
                reconcile = self._reconcile_context_on_recover(pos)
                reconcile["state_last_tv_side"] = saved_state_tv_side
                reconcile_notes = reconcile["notes"]
                real_amt = self._safe_qty(pos["size"])
                side = "LONG" if pos.get("posSide") == "long" else "SHORT"
                self.current_side = side

                if reconcile.get("tv_close"):
                    from app.core.startup_reconcile import should_skip_startup_tv_close_flatten
                    skip_flat, skip_reason = should_skip_startup_tv_close_flatten(self, reconcile)
                    if skip_flat:
                        reconcile["tv_close"] = False
                        reconcile_notes.append(f"跳过 TV CLOSE 清场 ({skip_reason})")
                        logger.info(
                            "🔄 [重启] TV CLOSE 但实盘同向 → 接管补挂不 flatten (%s)",
                            skip_reason,
                        )
                    else:
                        logger.warning("🔄 [重启] TV 最新为平仓指令，执行清场")
                        self._close_all(
                            f"🔄 重启对账: TV已发{(self.last_tv_signal or {}).get('action', 'CLOSE')}，执行清场"
                        )
                        return

                saved_initial = self._safe_qty(self.initial_qty)
                open_log_qty = self._safe_qty(reconcile.get("open_log_qty") or 0)
                if open_log_qty <= 0:
                    prepare_manual_adopt(self)
                    if hasattr(self, "_alert"):
                        self._alert(
                            "warning",
                            "STARTUP",
                            "未登记来源仓位 · 系统接管",
                            "未登记来源仓位·系统接管（来源待核实）",
                            {
                                "adopt_source": "unregistered_live",
                                "side": self.current_side,
                                "qty": real_amt,
                                "entry": float(pos.get("entry_price") or 0),
                                "source_verified": False,
                            },
                        )
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
                # 妈妈版：永不推断加仓次数
                self.add_count = 0
                self.watched_entry = float(pos["entry_price"])
                if hasattr(self, "_recompute_vps_hard_sl"):
                    from app.core.startup_reconcile import recompute_vps_hard_sl_on_recovery
                    recompute_vps_hard_sl_on_recovery(
                        self, entry_px=self.watched_entry, side=self.current_side,
                    )
                qty_change = reconcile.get("qty_manual_change")

                side_sync = self._try_force_align_opposite_to_tv(
                    reconcile,
                    adopted_manual=bool(
                        getattr(self, "adopted_manual", False)
                        or not reconcile.get("open_log_qty")
                    ),
                    trigger="startup",
                )
                if side_sync.get("paused"):
                    reconcile_notes.append(
                        f"方向不一致已暂停 · 实盘{side_sync.get('live_side')} vs TV{side_sync.get('tv_side')}"
                    )
                    summary = " | ".join(reconcile_notes)
                    self.monitoring = False
                    self._save_state()
                    self._dt.report_recover_takeover(
                        side=side,
                        qty=real_amt,
                        entry=self.watched_entry,
                        summary=f"PAUSED · {summary}",
                    )
                    return
                if side_sync.get("force_aligned"):
                    reconcile_notes.append(
                        f"逆势强平对齐 TV {side_sync.get('tv_side')} "
                        f"(原实盘{side_sync.get('live_side')})"
                    )
                    summary = " | ".join(reconcile_notes) if reconcile_notes else "逆势持仓已强平"
                    self._dt.report_recover_takeover(
                        side=side_sync.get("tv_side") or side,
                        qty=0,
                        entry=self.watched_entry,
                        summary=f"FORCE_ALIGN · {summary}",
                    )
                    if hasattr(self, "_alert"):
                        self._alert(
                            "critical",
                            "FORCE_ALIGN",
                            "VPS 重启 · 方向不一致强制平仓对齐 TV",
                            summary,
                            {"force_aligned": True, **side_sync},
                        )
                    return

                # Checklist §六: old radar schema → alert + pause (parity with Binance)
                if bool(getattr(self, "_state_schema_legacy", False)) and (
                    float(getattr(self, "initial_atr", 0) or 0) <= 0
                    or float(getattr(self, "initial_stop", 0) or 0) <= 0
                ):
                    msg = "重启检测到旧雷达schema(activated/stepCount)且无initialAtr · 暂停交易"
                    if hasattr(self, "_pause_trading"):
                        self._pause_trading(msg, {
                            "schema_legacy": True,
                            "side": side,
                            "qty": real_amt,
                        })
                    self.monitoring = False
                    self._save_state()
                    self._dt.report_recover_takeover(
                        side=side, qty=real_amt, entry=self.watched_entry,
                        summary=f"PAUSED · {msg}",
                    )
                    return

                has_persist_tp = any(float(x or 0) > 0 for x in (self.tv_tps or []))
                has_breath = (
                    float(getattr(self, "initial_atr", 0) or 0) > 0
                    and (
                        float(getattr(self, "initial_stop", 0) or 0) > 0
                        or float(getattr(self, "current_sl", 0) or 0) > 0
                    )
                )
                if not has_persist_tp or not has_breath:
                    if not has_persist_tp:
                        msg = "重启有持仓但无持久化 TP1/TP2/TP3 · 暂停交易"
                    else:
                        msg = "重启有持仓但无呼吸止损状态(initial_atr/initial_stop) · 暂停交易"
                    if hasattr(self, "_pause_trading"):
                        self._pause_trading(msg, {
                            "side": side, "qty": real_amt, "entry": self.watched_entry,
                            "initial_atr": getattr(self, "initial_atr", 0),
                            "initial_stop": getattr(self, "initial_stop", 0),
                            "current_sl": getattr(self, "current_sl", 0),
                        })
                    self.monitoring = False
                    self._save_state()
                    self._dt.report_recover_takeover(
                        side=side, qty=real_amt, entry=self.watched_entry,
                        summary=f"PAUSED · {msg}",
                    )
                    return

                if float(self.current_sl or 0) <= 0:
                    self.current_sl = float(
                        getattr(self, "initial_stop", 0) or getattr(self, "tv_sl", 0) or 0
                    )

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
                if hasattr(self, "_clear_position_local_state"):
                    self._clear_position_local_state()
                else:
                    self.watched_qty = 0
                    self.watched_entry = 0.0
                    self.initial_qty = 0
                    self.base_qty = 0
                    self.add_count = 0
                    self.current_side = None
                    self.best_price = 0.0
                    self.current_sl = 0.0
                    self.initial_stop = 0.0
                    self.initial_atr = 0.0
                    self.breakeven_phase = False
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

