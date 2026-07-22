import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.core.binance_client import BinanceClient
from app.core.adverse_radar_guard import AdverseRadarMixin, parse_tv_sl
from app.core.startup_reconcile import (
    StartupReconcileMixin,
    apply_tv_sl_from_sources,
    finalize_recovery_tv_params,
    format_startup_defense_summary,
    is_tv_close_action,
    live_matches_entry_direction,
    prepare_manual_adopt,
    recovery_section,
    should_ignore_bare_close_after_open,
    should_ignore_late_close_after_open,
    should_skip_tv_close_for_manual,
)
from app.core.binance_smart_defense import BinanceSmartDefenseMixin
from app.core.position_cap_guard import PositionCapGuardMixin
from app.core.position_manager import PositionManager
from app.core.radar_trail import clamp_stop_market_safe, tp_path_progress
from app.core.vps_radar_stages import (
    detect_radar_stage,
    tp1_filled_from_consumed,
)
from app.core.tp_regime_targets import build_regime_settings, enrich_tp_alert_detail
from app.core.regime_utils import clamp_regime
from app.core.same_direction_policy import (
    SameDirAction,
    evaluate_same_direction,
    format_refresh_reason,
    format_reopen_reason,
)
from app.core.close_attribution import diagnose_flat_close, format_close_reason
from app.core.symbol_precision import normalize_tv_targets, round_price, round_quantity, PRICE_TICK
from app.core.position_sizing import read_contract_equity
from app.core.tv_entry_sizing import (
    parse_tv_entry_fields,
    resolve_vps_entry_qty_eth,
)
from app.core.position_qty_tolerance import qty_change_significant, qty_drift_tolerance, tp_slice_qty_tolerance
from app.core.position_exposure_guard import resolve_booked_side
from app.core.tp_defense_reconcile import tp_price_matches
from app.core.tp_slice_guard import (
    compute_tp_slices,
    infer_filled_tp_levels,
    match_qty_reduction_to_tp_level,
    resolve_tp_step_fill_level,
)
from app.services.tv_signal_enrich import format_enrich_note, merge_supervisor_fallbacks
from app.services.close_alert_utils import (
    build_close_detail,
    build_verify_note,
    extract_tv_close_fields,
    format_close_dingtalk_message,
    resolve_close_alert_title,
    resolve_close_alert_type,
)
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
SENTINEL_POLL_NORMAL = 5.0
# Near TP1 / TP fill monitor (REST book) — dual-symbol rate-limit safe
SENTINEL_POLL_ARMING = 1.0
# Radar engaged: trail on markPrice WS; REST sentinel at 1s + jitter
SENTINEL_POLL_RADAR = 1.0
# Order-book / TP audit REST cadence (fills prefer user-data WS invalidate)
SENTINEL_ORDER_AUDIT_SEC = 2.0
# WS tick → radar evaluate throttle (avoid place/cancel thrash)
RADAR_WS_TICK_MIN_SEC = 0.45
SENTINEL_POLL_JITTER_SEC = 0.2
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


class PositionSupervisor(
    PositionCapGuardMixin, AdverseRadarMixin, BinanceSmartDefenseMixin, StartupReconcileMixin,
):
    """
    多用户版 position_supervisor_binance.py
    TV 军师指挥价格/regime → VPS 自主执行仓位管理、止盈网格、雷达锁润、先平后开、单向持仓。
    Binance / OKX / Gate 共用本类；Deepcoin 通过 parallel 适配层保持相同 TP/雷达语义。
    """

    def __init__(
        self,
        user_id: int,
        client: BinanceClient,
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
            label_for_symbol,
            normalize_canonical_symbol,
            qty_unit_for_symbol,
            supervisor_state_key,
        )
        from app.core.symbol_precision import min_qty_for

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

        self.canonical_symbol = (
            normalize_canonical_symbol(canonical_symbol)
            or getattr(client, "canonical_symbol", None)
            or DEFAULT_CANONICAL
        )
        self.symbol = getattr(client, "trading_symbol", None) or settings.SYMBOL
        self.exchange_id = getattr(client, "exchange_id", "binance")
        from app.core.tv_entry_sizing import FIXED_LEVERAGE
        self.leverage = int(
            getattr(client, "trading_leverage", None) or FIXED_LEVERAGE
        )
        self.qty_unit = qty_unit_for_symbol(self.canonical_symbol, self.exchange_id)
        self.symbol_label = label_for_symbol(self.canonical_symbol)
        self.min_order_qty = min_qty_for(self.canonical_symbol)
        self.monitoring = False
        self._lock = threading.Lock()
        self._signal_queue: queue.Queue[_QueuedSignal] = queue.Queue()
        self._queue_worker_lock = threading.Lock()
        self._queue_worker_started = False
        self.trade_opened_at: float | None = None
        self._radar_ws_tick_ts: float = 0.0
        self._radar_ws_bound: bool = False

        # activation / move_step / trail_offset from REGIME_RADAR (radar_trail.py)
        self.regime_settings = build_regime_settings()

        self.regime = 3
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
        self._tp_placed_at = {}  # level -> unix ts
        self._defense_order_ids = {}  # "1"|"2"|"sl" -> orderId
        self.current_sl = 0.0
        self.tv_price = 0.0
        self.initial_qty = 0.0
        self.base_qty = 0.0
        self.add_count = 0
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_side = None
        self.last_tv_side = None
        self.tv_tps = [0.0, 0.0, 0.0]
        self.current_trade_id = None
        self.risk_multiplier = 1.0
        self.consumed_tp_levels: list[int] = []
        self.adopted_manual = False
        self._scan_ticks = 0
        self._last_tp_audit_ts = 0.0
        self._init_adverse_radar_fields()

        state_key = supervisor_state_key(self.exchange_id, user_id, self.canonical_symbol)
        base_dir = os.path.join("data", "supervisor", state_key)
        os.makedirs(base_dir, exist_ok=True)
        self.state_file = os.path.join(base_dir, "state.json")
        # Migrate legacy single-file state for ETH only
        legacy = f"state/user_{user_id}.json"
        if (
            self.canonical_symbol == DEFAULT_CANONICAL
            and not os.path.exists(self.state_file)
            and os.path.exists(legacy)
        ):
            try:
                import shutil
                shutil.copy2(legacy, self.state_file)
            except Exception:
                pass
        self._load_state()
        self._start_idle_flat_patrol()

    def _round_qty(self, value) -> float:
        return round_quantity(value, self.canonical_symbol)

    def _round_px(self, value) -> float:
        return round_price(value, self.canonical_symbol)

    def _symbol_tag(self) -> str:
        from app.core.breathing_profile import symbol_tag
        can = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        return f"[{symbol_tag(can)}]"

    def _log(self, event_type: str, message: str, detail: dict | None = None):
        tag = self._symbol_tag()
        msg = message if str(message).startswith(tag) else f"{tag} {message}"
        payload = dict(detail or {})
        can = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        if can:
            payload.setdefault("canonical_symbol", can)
            payload.setdefault("symbol", can)
        self.on_log(self.user_id, event_type, msg, payload, self.current_trade_id)

    def _alert(self, severity: str, alert_type: str, title: str, message: str, detail: dict | None = None):
        payload = dict(detail or {})
        can = getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None)
        if can:
            payload.setdefault("canonical_symbol", can)
            payload.setdefault("symbol", can)
        if getattr(self, "qty_unit", None):
            payload.setdefault("qty_unit", self.qty_unit)
        ex = getattr(self, "exchange_id", None) or getattr(self, "exchange", None)
        if ex:
            payload.setdefault("exchange", ex)
        # Execution-context snapshot — never let theme/config invent leverage
        if hasattr(self, "_resolve_entry_leverage"):
            try:
                payload["leverage"] = int(self._resolve_entry_leverage())
            except Exception:
                payload.setdefault(
                    "leverage", int(getattr(self, "leverage", 0) or 0) or None,
                )
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
        tag = self._symbol_tag()
        titled = title if str(title).startswith(tag) else f"{tag} {title}"
        msg = message if str(message).startswith(tag) else f"{tag} {message}"
        self.on_alert(self.user_id, severity, alert_type, titled, msg, payload)

    def _save_state(self):
        try:
            with open(self.state_file, "w") as f:
                json.dump({
                    "schema_version": 2,
                    "last_tv_side": self.last_tv_side,
                    "current_side": self.current_side,
                    "watched_qty": self.watched_qty,
                    "watched_entry": self.watched_entry,
                    "current_sl": self.current_sl,
                    "best_price": self.best_price,
                    "regime": self.regime,
                    "current_atr": self.current_atr,
                    "initial_atr": float(getattr(self, "initial_atr", 0) or 0),
                    "initial_stop": float(getattr(self, "initial_stop", 0) or 0),
                    "breakeven_phase": bool(getattr(self, "breakeven_phase", False)),
                    "breathing_coefficient": float(getattr(self, "breathing_coefficient", 1.0) or 1.0),
                    "breath_ratio_history": list(getattr(self, "breath_ratio_history", None) or []),
                    "atr_1h": float(getattr(self, "atr_1h", 0) or 0),
                    "breath_smooth_ratio": float(getattr(self, "breath_smooth_ratio", 1.0) or 1.0),
                    "tv_atr_ref": float(getattr(self, "_tv_atr_ref", 0) or 0),
                    "current_adx": float(getattr(self, "current_adx", 25) or 25),
                    "remaining_qty_pct": float(getattr(self, "remaining_qty_pct", 1.0) or 1.0),
                    "monitoring": self.monitoring,
                    "tv_tps": self.tv_tps,
                    "initial_qty": self.initial_qty,
                    "base_qty": float(getattr(self, "base_qty", 0) or 0),
                    "add_count": 0,
                    "consumed_tp_levels": self.consumed_tp_levels,
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
                    "atr_mismatch_streak": int(getattr(self, "atr_mismatch_streak", 0) or 0),
                    "atr_fallback_active": bool(getattr(self, "atr_fallback_active", False)),
                    "current_trade_id": getattr(self, "current_trade_id", None),
                    "canonical_symbol": getattr(self, "canonical_symbol", None),
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
                    self.initial_atr = float(s.get("initial_atr", 0) or 0)
                    self.initial_stop = float(s.get("initial_stop", 0) or 0)
                    self.breakeven_phase = bool(s.get("breakeven_phase", False))
                    self.breathing_coefficient = float(s.get("breathing_coefficient", 1.0) or 1.0)
                    self.breath_ratio_history = [
                        float(x) for x in (s.get("breath_ratio_history") or [])
                    ]
                    self.atr_1h = float(s.get("atr_1h", 0) or 0)
                    self.breath_smooth_ratio = float(s.get("breath_smooth_ratio", 1.0) or 1.0)
                    self._tv_atr_ref = float(s.get("tv_atr_ref", 0) or 0)
                    self.current_adx = float(s.get("current_adx", 25) or 25)
                    self.remaining_qty_pct = float(s.get("remaining_qty_pct", 1.0) or 1.0)
                    # Old radar schema detection (activated/stepCount without breathing fields)
                    has_old = (
                        ("radar_activated" in s or "radar_step_count" in s or "step_count" in s)
                        and float(s.get("initial_atr", 0) or 0) <= 0
                    )
                    self._state_schema_legacy = bool(has_old) or int(s.get("schema_version") or 0) < 2
                    self.monitoring = bool(s.get("monitoring", False))
                    self.initial_qty = float(s.get("initial_qty", 0) or 0)
                    self.base_qty = float(s.get("base_qty", 0) or s.get("initial_qty", 0) or 0)
                    self.add_count = 0
                    self.tv_tps = normalize_tv_targets(s.get("tv_tps", [0.0, 0.0, 0.0]))
                    self.consumed_tp_levels = [
                        int(x) for x in (s.get("consumed_tp_levels") or []) if int(x) in (1, 2, 3)
                    ]
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
                    self.atr_mismatch_streak = max(int(s.get("atr_mismatch_streak", 0) or 0), 0)
                    self.atr_fallback_active = bool(s.get("atr_fallback_active", False))
                    tid = s.get("current_trade_id")
                    if tid is not None:
                        try:
                            self.current_trade_id = int(tid)
                        except (TypeError, ValueError):
                            pass
                    self._infer_radar_latched_from_state()
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
        payload = merge_supervisor_fallbacks(
            payload,
            regime=self.regime,
            atr=self.current_atr,
        )
        raw_action = str(payload.get("action", "")).upper()
        blocked = self._block_if_trading_paused(raw_action) if hasattr(self, "_block_if_trading_paused") else None
        if blocked:
            return blocked
        enrich_note = format_enrich_note(payload)
        self._last_enrich_note = enrich_note
        signal_detail = {
            "action": payload.get("action"),
            "side": payload.get("side"),
            "price": payload.get("price"),
            "tv_tp1": payload.get("tv_tp1"),
            "tv_tp2": payload.get("tv_tp2"),
            "tv_tp3": payload.get("tv_tp3"),
            "tv_sl": payload.get("tv_sl"),
            "regime": payload.get("regime"),
            "atr": payload.get("atr"),
            "entry_type": payload.get("entry_type"),
            "qty_ratio": payload.get("qty_ratio"),
            "reason": payload.get("reason"),
            "bar_index": payload.get("bar_index"),
            "seq": payload.get("seq"),
            "enrich_note": enrich_note,
        }
        self._log(
            "SIGNAL_RECV",
            f"TV → {payload.get('action')} bar={payload.get('bar_index')} seq={payload.get('seq')}",
            signal_detail,
        )
        raw_action = str(payload.get("action", "")).upper()

        # UPDATE_TP before mutating regime/atr/tv_sl — only replaces TP limits.
        if raw_action == "UPDATE_TP":
            return self._handle_update_tp(payload)

        held_regime = self.regime
        held_atr = self.current_atr
        prev_tv_tps = list(self.tv_tps)
        self._signal_prev_tv_tps = prev_tv_tps
        self.regime = int(payload.get("regime", 3))
        self.regime = clamp_regime(self.regime)

        # Prefer TV webhook atr as frozen initial_atr; VPS 90m only as fallback
        position_open = bool(
            getattr(self, "monitoring", False)
            or float(getattr(self, "watched_qty", 0) or 0) > 0
        )
        tv_atr_raw = payload.get("atr")
        try:
            tv_atr = float(tv_atr_raw) if tv_atr_raw is not None and tv_atr_raw != "" else 0.0
        except (TypeError, ValueError):
            tv_atr = 0.0
        if tv_atr > 0:
            self._tv_atr_ref = tv_atr
            if not position_open:
                self.current_atr = tv_atr
        self.tv_price = round_price(payload.get("price", 0))
        self.tv_tps = normalize_tv_targets([
            payload.get("tv_tp1", 0),
            payload.get("tv_tp2", 0),
            payload.get("tv_tp3", 0),
        ])
        self.risk_multiplier = float(payload.get("risk_multiplier", 1.0))
        if not position_open and hasattr(self, "_pull_vps_market_indicators"):
            # Soft fallback only when TV atr missing
            if float(getattr(self, "_tv_atr_ref", 0) or 0) <= 0:
                self._pull_vps_market_indicators(force=True)
        self._apply_tv_entry_context(payload)
        self._apply_tv_sl_from_payload(payload)
        close_reason = payload.get("reason", "策略指标反转/波动率安全退出")
        tv_side = str(payload.get("side") or "").upper().strip() or None
        tv_pnl_pct = payload.get("pnl_pct")
        if tv_pnl_pct is not None:
            try:
                tv_pnl_pct = float(tv_pnl_pct)
            except (TypeError, ValueError):
                tv_pnl_pct = None

        self.monitoring = False
        tv_close = extract_tv_close_fields(payload)
        tv_reason = tv_close.get("tv_reason") or close_reason

        if is_tv_close_action(raw_action):
            skip, skip_reason = should_skip_tv_close_for_manual(self, raw_action)
            if skip:
                return self._preserve_manual_on_tv_close(
                    raw_action, skip_reason=skip_reason, tv_reason=tv_reason,
                )
            ignore, ignore_reason = should_ignore_bare_close_after_open(self, raw_action)
            if ignore:
                self._log("SIGNAL", f"⏭️ {ignore_reason}", {"action": raw_action, "tv_reason": tv_reason})
                self._alert(
                    "info",
                    "CLOSE_DEFER",
                    "开仓保护期 · 忽略裸 CLOSE",
                    ignore_reason,
                    {"action": raw_action, "tv_reason": tv_reason, "regime": self.regime},
                )
                return {
                    "status": "skipped",
                    "reason": "open_grace_bare_close",
                    "message": ignore_reason,
                }
            late, late_reason = should_ignore_late_close_after_open(self, raw_action)
            if late:
                self._log("SIGNAL", f"⏭️ {late_reason}", {"action": raw_action, "tv_reason": tv_reason})
                self._alert(
                    "info",
                    "CLOSE_DEFER",
                    "开仓保护期 · 忽略迟到平仓",
                    late_reason,
                    {"action": raw_action, "tv_reason": tv_reason, "regime": self.regime},
                )
                return {
                    "status": "skipped",
                    "reason": "open_grace_late_close",
                    "message": late_reason,
                }

        def _tv_close_kwargs() -> dict:
            return {
                "tv_side": tv_side or tv_close.get("tv_side"),
                "tv_pnl_pct": tv_pnl_pct if tv_pnl_pct is not None else tv_close.get("tv_pnl_pct"),
                "tv_close_ctx": tv_close,
                "tv_reason": tv_reason,
            }

        # v6.5.6: reconcile-only closes — no market order (limits/radar already filled)
        from app.services.webhook_guard import (
            is_force_flat_close,
            is_reconcile_only_close,
        )
        if is_reconcile_only_close(raw_action):
            return self._handle_tv_reconcile_close(raw_action, payload, tv_reason=tv_reason)
        if is_force_flat_close(raw_action):
            self._close_all(
                f"⚡ 策略反转全平：{tv_reason or raw_action}",
                close_action=raw_action,
                **_tv_close_kwargs(),
            )
            return {"status": "ok", "action": raw_action, "detail": {"type": "force_flat"}}
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

    def _handle_tv_reconcile_close(
        self, action: str, payload: dict | None = None, *, tv_reason: str | None = None,
    ) -> dict:
        """Checklist §2B: reconcile-only + optional SL bump; NEVER market flatten."""
        payload = payload or {}
        leg = str(payload.get("leg") or "").strip()
        qty = float(payload.get("qty") or 0)
        price = float(payload.get("price") or 0)
        pos = self._get_position() if hasattr(self, "_get_position") else None
        live_qty = float((pos or {}).get("size") or (pos or {}).get("qty") or 0)
        # Prefer live exchange qty via position_manager when available
        try:
            live_pos = self.position_manager.get_position(self.symbol)
            if live_pos is not None:
                live_qty = abs(float(live_pos.get("positionAmt") or live_pos.get("size") or 0))
        except Exception:
            pass
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
            # §4: raise remaining SL after TP fills
            if live_qty > 0 and hasattr(self, "_bump_sl_after_tp_reconcile"):
                try:
                    bump = self._bump_sl_after_tp_reconcile(leg)
                    detail["sl_bump"] = bump
                except Exception as exc:
                    detail["sl_bump_error"] = str(exc)
            if hasattr(self, "_save_state"):
                self._save_state()
        # CLOSE_TRAIL leg=2 same as CLOSE_TP leg=2 (§三 B)
        if action == "CLOSE_TRAIL" and leg == "2":
            try:
                consumed = set(getattr(self, "consumed_tp_levels", None) or [])
                consumed.add(2)
                self.consumed_tp_levels = sorted(consumed)
            except Exception:
                pass
            if live_qty > 0 and hasattr(self, "_bump_sl_after_tp_reconcile"):
                try:
                    detail["sl_bump"] = self._bump_sl_after_tp_reconcile("2")
                except Exception as exc:
                    detail["sl_bump_error"] = str(exc)
            if hasattr(self, "_save_state"):
                self._save_state()
        if action in ("CLOSE_TRAIL", "CLOSE_SL_INITIAL", "CLOSE_SL_BREAKEVEN") or (
            action == "CLOSE_TP" and leg == "3"
        ):
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
                detail["radar_reset"] = True
                detail["local_state_cleared"] = True
        elif live_qty <= 0:
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
        """After TP fill: update remaining_qty_pct and resize stop qty (no price bump)."""
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

    def _apply_tv_entry_context(self, payload: dict) -> None:
        fields = parse_tv_entry_fields(payload)
        self._tv_entry_fields = fields
        self._entry_type = fields["entry_type"]
        self._explicit_entry_type = "entry_type" in (payload or {})
        if fields.get("regime") is not None:
            self._tv_entry_fields["regime"] = fields["regime"]
        elif getattr(self, "regime", None):
            self._tv_entry_fields["regime"] = self.regime
        # Persist leverage on supervisor immediately (live OPEN binds FIXED_LEVERAGE=5)
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

    def _resolve_entry_qty(self, curr_px: float) -> tuple[float, dict]:
        """Sizing once at open: equity×20%×5 (=1× notional). ATR from TV webhook.

        initialStop = entry ± 1.5×ATR ± 0.3 buffer (exchange hang).
        TV stop_loss is never the exchange stop price.
        """
        from app.core.breathing_stop import compute_initial_stop
        from app.core.open_atr_guard import check_open_atr_or_reject

        equity = read_contract_equity(self.client)
        leverage = self._resolve_entry_leverage()
        tv_fields = getattr(self, "_tv_entry_fields", None) or {}
        tv_qty = tv_fields.get("tv_qty")
        price = float(curr_px or self.tv_price or 0)
        side = str(getattr(self, "_pending_open_side", None) or getattr(self, "current_side", None) or "").upper()
        if side not in ("LONG", "SHORT"):
            side = str(getattr(self, "last_tv_side", None) or "").upper()

        snap: dict = {}
        tv_atr = float(getattr(self, "_tv_atr_ref", 0) or 0)
        if tv_atr <= 0:
            try:
                tv_atr = float(tv_fields.get("atr") or 0)
            except (TypeError, ValueError):
                tv_atr = 0.0
        if tv_atr <= 0 and hasattr(self, "_pull_vps_market_indicators"):
            try:
                snap = self._pull_vps_market_indicators(force=True) or {}
            except Exception:
                snap = {}
        atr = float(tv_atr or snap.get("atr") or getattr(self, "current_atr", 0) or 0)
        atr_series = list(snap.get("atr_series") or [])
        atr_source = "tv_webhook" if tv_atr > 0 else "vps"
        tv_sl_ref = self._pine_stop_loss_ref() if hasattr(self, "_pine_stop_loss_ref") else float(
            getattr(self, "_tv_stop_loss_ref", 0)
            or getattr(self, "_pending_open_tv_sl", 0)
            or 0
        )
        self._atr_fallback_pending_pause = False
        self.atr_fallback_active = False
        fb: dict = {}

        atr_ok, atr_meta = check_open_atr_or_reject(
            self,
            atr=atr,
            atr_series=atr_series,
            side=side,
            tv_sl_ref=tv_sl_ref if tv_sl_ref > 0 else None,
        )
        if not atr_ok:
            return 0.0, atr_meta

        if hasattr(self, "_save_state"):
            try:
                self._save_state()
            except Exception:
                pass

        sizing_stop = 0.0
        if atr > 0 and price > 0 and side in ("LONG", "SHORT"):
            sizing_stop = float(compute_initial_stop(price, side, atr))

        qty, meta = resolve_vps_entry_qty_eth(
            live_balance=equity,
            initial_principal=self.initial_principal,
            entry_type="OPEN",
            base_qty=0.0,
            price=price,
            tv_sl=sizing_stop,
            tv_stop_loss=tv_sl_ref if tv_sl_ref > 0 else None,
            regime=int(self.regime or 3),
            exchange_leverage=leverage,
            round_fn=self._round_qty,
            symbol=self.canonical_symbol,
            min_qty=float(getattr(self, "min_order_qty", 0) or 0) or None,
            tv_qty=float(tv_qty) if tv_qty else None,
        )
        meta["tv_sl_reference"] = tv_sl_ref if tv_sl_ref > 0 else None
        meta["sizing_stop"] = round(sizing_stop, 4) if sizing_stop else None
        meta["sizing_atr"] = round(atr, 4) if atr else None
        meta["sizing_side"] = side or None
        meta["atr_source"] = atr_source
        meta["atr_fallback"] = False
        meta["atr_fallback_detail"] = fb
        if sizing_stop > 0:
            self._sizing_initial_stop = sizing_stop
            self.initial_atr = atr if atr > 0 else float(getattr(self, "initial_atr", 0) or 0)
            self.current_atr = self.initial_atr
        self._log(
            "SIGNAL",
            "📐 开仓算仓 "
            f"atr_src={atr_source} "
            f"notional={meta.get('notional_target') or meta.get('candidate_qty_by_notional')} "
            f"bind={meta.get('binding')} "
            f"final={meta.get('final_qty')}"
            + (f" err={meta.get('error')}" if meta.get("error") else ""),
        )
        if qty > 0:
            from app.core.combined_notional import check_combined_notional_cap

            notional = float(meta.get("notional_usd") or meta.get("position_value") or 0)
            if notional <= 0 and price:
                notional = qty * float(price)
            ok, cap_meta = check_combined_notional_cap(
                user_id=self.user_id,
                canonical=self.canonical_symbol,
                equity=equity if equity > 0 else self.initial_principal,
                new_notional=notional,
            )
            meta.update(cap_meta)
            if not ok:
                return 0.0, meta
        return qty, meta
    def _max_add_times(self) -> int:
        """妈妈版 pyramiding=1 — 加仓禁用."""
        return 0

    def _can_add_more(self) -> tuple[bool, str]:
        return False, "加仓已禁用（妈妈版单仓）"

    def _handle_tv_entry(
        self,
        action: str,
        curr_px: float,
        *,
        has_pos: bool,
        current_side: str | None,
    ) -> dict:
        """权威规格：LONG/SHORT 一律先平后开，永不加仓。"""
        self._pending_open_side = str(action or "").upper()
        self._log(
            "SIGNAL",
            f"⚡ TV OPEN [{action}] 铁律·先平后开（单仓·无加仓）",
        )
        if not self._force_flat_before_open(f"TV OPEN [{action}] 铁律·先平后开"):
            return {"status": "error", "reason": "flat_timeout", "message": "平仓未确认归零"}
        return self._open_position(action, curr_px)

    def _add_to_position(self, action: str, curr_px: float, entry_type: str) -> dict:
        """Disabled — redirect to flatten+open."""
        self._log("SIGNAL", f"⏭️ {entry_type} 加仓已禁用 → 降级先平后开")
        if not self._force_flat_before_open(f"{entry_type}禁用·先平后开"):
            return {"status": "error", "reason": "flat_timeout", "message": "平仓未确认归零"}
        return self._open_position(action, curr_px)

    def _read_live_position_snapshot(self) -> tuple[str | None, float, float]:
        """Return (side, qty, entry) from exchange — Binance-style or DeepCoin."""
        if hasattr(self, "_get_active_position"):
            pos = self._get_active_position()
            if not pos:
                return None, 0.0, 0.0
            qty = float(self._safe_qty(pos.get("size"))) if hasattr(self, "_safe_qty") else float(pos.get("size") or 0)
            if qty <= 0:
                return None, 0.0, 0.0
            side = str(pos.get("side") or "").upper()
            if side not in ("LONG", "SHORT"):
                ps = str(pos.get("posSide") or "").lower()
                side = "LONG" if ps == "long" else ("SHORT" if ps == "short" else None)
            entry = float(pos.get("entry_price") or pos.get("entryPrice") or 0)
            return side, qty, entry
        pos = self.position_manager.get_position(self.symbol)
        live_amt = float(pos.get("positionAmt", 0) or 0) if pos else 0.0
        live_side = "LONG" if live_amt > 0 else ("SHORT" if live_amt < 0 else None)
        return live_side, abs(live_amt), float(pos.get("entryPrice", 0) or 0) if pos else 0.0

    def _reconcile_live_vs_book(
        self,
        *,
        expect_side: str | None = None,
        expect_qty: float | None = None,
        expect_flat: bool = False,
        context: str = "",
        notify_ok: bool = False,
    ) -> dict:
        """Query exchange position and compare to expected post-signal state."""
        try:
            live_side, live_qty, live_entry = self._read_live_position_snapshot()
        except Exception as e:
            detail = {
                "context": context,
                "error": str(e),
                "exchange": getattr(self, "exchange_id", None),
            }
            self._log("POSITION_RECONCILE", f"对账失败·查仓异常 [{context}]", detail)
            self._alert(
                "warning",
                "POSITION_RECONCILE",
                "头寸对账失败·查仓异常",
                f"{context}: {e}",
                detail,
            )
            return detail

        ok = True
        mismatch = ""
        if expect_flat:
            if live_qty > 0:
                ok = False
                mismatch = f"期望空仓但盘口仍有 {live_side} {live_qty}"
        elif expect_side:
            if live_side != str(expect_side).upper() or live_qty <= 0:
                ok = False
                mismatch = (
                    f"期望 {expect_side} 持仓，盘口为 "
                    f"{live_side or '空仓'} {live_qty}"
                )
            elif expect_qty is not None and expect_qty > 0:
                tol = max(expect_qty * 0.08, 0.001)
                if abs(live_qty - float(expect_qty)) > tol:
                    ok = False
                    mismatch = f"数量偏差 账本{expect_qty} vs 盘口{live_qty}"

        detail = {
            "exchange": getattr(self, "exchange_id", None),
            "context": context,
            "ok": ok,
            "expect_side": expect_side,
            "expect_qty": expect_qty,
            "expect_flat": expect_flat,
            "live_side": live_side,
            "live_qty": live_qty,
            "live_entry": live_entry,
            "book_side": getattr(self, "current_side", None),
            "book_qty": float(getattr(self, "watched_qty", 0) or 0),
            "mismatch": mismatch or None,
        }
        if ok:
            self._log(
                "POSITION_RECONCILE",
                f"对账一致 [{context}] {live_side or 'FLAT'} {live_qty}",
                detail,
            )
            if notify_ok:
                self._alert(
                    "info",
                    "POSITION_RECONCILE",
                    f"头寸对账一致·{context}",
                    f"盘口 {live_side or '空仓'} {live_qty} @ {live_entry or '—'}",
                    detail,
                )
        else:
            self._log("POSITION_RECONCILE", f"对账不一致 [{context}] {mismatch}", detail)
            self._alert(
                "warning",
                "POSITION_RECONCILE",
                f"头寸对账不一致·{context}",
                mismatch or "账本与交易所不符",
                detail,
            )
        return detail

    def _count_open_book_orders(self) -> int:
        """TP limits + conditional stops still on the exchange book."""
        n = 0
        try:
            if hasattr(self, "_collect_tp_limit_orders"):
                n += len(self._collect_tp_limit_orders() or [])
            elif hasattr(self.client, "get_open_orders"):
                n += len(self.client.get_open_orders(self.symbol) or [])
        except Exception:
            pass
        try:
            if hasattr(self, "_collect_adverse_stop_orders"):
                n += len(self._collect_adverse_stop_orders() or [])
            elif hasattr(self, "_collect_stop_orders"):
                n += len(self._collect_stop_orders() or [])
        except Exception:
            pass
        return int(n)

    def _ensure_book_clean_before_open(self, reason: str = "pre_open") -> dict:
        """
        After flat (or before OPEN): wipe residual TP/stop so a fast CLOSE→OPEN
        cannot leave reverse/oversize fills from stale reduce-only orders.
        """
        detail: dict = {
            "reason": reason,
            "exchange": getattr(self, "exchange_id", None),
            "rounds": 0,
            "orders_before": 0,
            "orders_after": 0,
            "ok": False,
        }
        detail["orders_before"] = self._count_open_book_orders()
        for round_i in range(3):
            detail["rounds"] = round_i + 1
            if hasattr(self, "_purge_defense_orders_on_flat"):
                self._purge_defense_orders_on_flat(f"pre_open_{reason}", notify=False)
            if hasattr(self, "_cancel_all_verified"):
                self._cancel_all_verified()
            elif hasattr(self.client, "cancel_all_open_orders"):
                self.client.cancel_all_open_orders(self.symbol)
            if hasattr(self, "_disarm_adverse_staged_stops"):
                self._disarm_adverse_staged_stops(reason="pre_open_clean", notify=False)
            # 必须保留本笔 TV 刚写入的 tv_sl（清的是旧仓雷达状态，不是新信号硬止损）
            if hasattr(self, "_reset_adverse_radar"):
                self._reset_adverse_radar(keep_tv_sl=True)
            self.consumed_tp_levels = []
            if hasattr(self, "radar_latched"):
                self.radar_latched = False
            time.sleep(0.35 + round_i * 0.15)
            left = self._count_open_book_orders()
            detail["orders_after"] = left
            if left <= 0:
                detail["ok"] = True
                break
        if not detail["ok"]:
            self._log(
                "FLIP_CLEAN",
                f"开仓前挂单未清零 remaining={detail['orders_after']} | {reason}",
                detail,
            )
            self._alert(
                "warning",
                "FLIP_CLEAN",
                "开仓前挂单残留·已尽力撤单",
                f"仍有 {detail['orders_after']} 笔挂单 | {reason} — 上层将中止开仓",
                detail,
            )
        else:
            if detail["orders_before"] > 0:
                self._log("FLIP_CLEAN", f"开仓前清场完成 撤尽 {detail['orders_before']} 笔 | {reason}", detail)
        if hasattr(self, "_save_state"):
            self._save_state()
        return detail

    def _force_flat_retry_delays(self) -> tuple[float, ...]:
        """Backoff seconds between close retries (default 1 / 3 / 6)."""
        raw = str(getattr(settings, "FORCE_FLAT_RETRY_DELAYS_SEC", "1,3,6") or "1,3,6")
        out: list[float] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(max(0.0, float(part)))
            except (TypeError, ValueError):
                continue
        return tuple(out) if out else (1.0, 3.0, 6.0)

    def _abort_force_flat(
        self,
        reason: str,
        *,
        fail_kind: str,
        detail: dict | None = None,
    ) -> bool:
        """平仓/清场失败：放弃本次开仓 + 暂停该 symbol + 高优钉钉（需人工介入）。"""
        meta = {"reason": reason, "fail_kind": fail_kind, **(detail or {})}
        self._log("ERROR", f"先平后开中止·{fail_kind}", meta)
        msg = (
            f"【需人工介入】{reason} — {fail_kind}；"
            f"已中止开仓并暂停本 symbol 自动开仓，确认交易所持仓后手动恢复"
        )
        self._alert(
            "critical",
            "FLIP_CLEAN_ABORT",
            "先平后开失败·需人工介入",
            msg,
            meta,
        )
        if hasattr(self, "_pause_trading"):
            try:
                self._pause_trading(f"先平后开失败·{fail_kind}", meta)
            except Exception as e:
                logger.warning("[User %s] pause after force_flat fail: %s", self.user_id, e)
        try:
            self._reconcile_live_vs_book(
                expect_flat=True, context="force_flat_abort", notify_ok=False,
            )
        except Exception:
            pass
        return False

    def _force_flat_before_open(self, reason: str) -> bool:
        """
        铁律：任意带开仓的 TV → 先干净平仓（仓位归零 + 撤尽 TP/雷达/硬止损），再开新仓。
        已空仓时仅清残留挂单/状态，不刷屏钉钉。
        注意：清场不得抹掉本笔 TV 已下发的 tv_sl（否则开仓算仓会 missing_tv_sl）。
        平仓失败：按 1s/3s/6s 重试；仍失败则中止开仓并暂停（严禁仓位不明时开新仓）。
        """
        # Preserve TV Pine stop_loss ref (not VPS hang price in self.tv_sl).
        pending_tv_sl = float(
            getattr(self, "_tv_stop_loss_ref", 0)
            or getattr(self, "_pending_open_tv_sl", 0)
            or 0
        )
        pending_hard = float(getattr(self, "_tv_hard_sl_price", 0) or 0)
        if pending_tv_sl > 0:
            self._tv_stop_loss_ref = pending_tv_sl
            self._pending_open_tv_sl = pending_tv_sl

        live = self._get_active_position() if hasattr(self, "_get_active_position") else None
        if live is None and hasattr(self, "position_manager"):
            raw = self.position_manager.get_position(self.symbol)
            if raw and float(raw.get("positionAmt", 0) or 0) != 0:
                amt = float(raw["positionAmt"])
                live = {"size": abs(amt), "side": "LONG" if amt > 0 else "SHORT"}
        already_flat = not live or float(live.get("size") or 0) <= 0

        if already_flat:
            self._log("SIGNAL", f"先平后开·已空仓→清挂单后开新仓 | {reason}")
            clean = self._ensure_book_clean_before_open(reason)
            if hasattr(self, "_clear_position_local_state"):
                self._clear_position_local_state()
            else:
                self.watched_qty = 0.0
                self.watched_entry = 0.0
                self.initial_qty = 0.0
                self.base_qty = 0.0
                self.add_count = 0
                self.consumed_tp_levels = []
                self._tp_fill_dingtalk_levels = set()
                self.current_side = None
            # Preserve pending TV Pine stop_loss for sizing/ATR (after wipe)
            if pending_tv_sl > 0:
                self._tv_stop_loss_ref = pending_tv_sl
                self._pending_open_tv_sl = pending_tv_sl
                if pending_hard > 0:
                    self._tv_hard_sl_price = pending_hard
            if hasattr(self, "radar_latched"):
                self.radar_latched = False
            if hasattr(self, "_save_state"):
                self._save_state()
            if not bool(clean.get("ok", True)):
                return self._abort_force_flat(
                    reason,
                    fail_kind="空仓但挂单未清零",
                    detail={"clean": clean},
                )
            return True

        self._log("SIGNAL", f"先平后开·清现有仓再刷新 | {reason}")
        delays = self._force_flat_retry_delays()
        flat_ok = False
        last_err: str | None = None
        for attempt, delay in enumerate(delays, start=1):
            # 先撤单再平仓，减少平仓瞬间旧 TP 误成
            if hasattr(self, "_purge_defense_orders_on_flat"):
                self._purge_defense_orders_on_flat(
                    f"force_flat_pre_{attempt}", notify=False,
                )
            try:
                if hasattr(self, "_cancel_all_verified"):
                    self._cancel_all_verified()
                else:
                    self.client.cancel_all_open_orders(self.symbol)
            except Exception as e:
                last_err = str(e)
                logger.warning(
                    "[User %s] force_flat cancel attempt %s: %s",
                    self.user_id, attempt, e,
                )
            time.sleep(0.45)
            try:
                self._close_all(
                    reason if attempt == 1 else f"{reason}·残仓扫尾#{attempt}",
                )
            except Exception as e:
                last_err = str(e)
                logger.warning(
                    "[User %s] force_flat close attempt %s: %s",
                    self.user_id, attempt, e,
                )
            wait_to = 5.0 if attempt > 1 else 8.0
            if self._wait_until_flat(timeout=wait_to):
                flat_ok = True
                break
            if attempt < len(delays) and delay > 0:
                self._log(
                    "SIGNAL",
                    f"先平后开·平仓未归零，{delay:g}s 后重试 ({attempt}/{len(delays)})",
                    {"reason": reason, "attempt": attempt, "last_err": last_err},
                )
                time.sleep(delay)

        if not flat_ok:
            return self._abort_force_flat(
                reason,
                fail_kind="平仓后仓位未归零",
                detail={
                    "attempts": len(delays),
                    "delays_sec": list(delays),
                    "last_err": last_err,
                },
            )

        clean = self._ensure_book_clean_before_open(reason)
        if hasattr(self, "_clear_position_local_state"):
            self._clear_position_local_state()
        else:
            self.watched_qty = 0.0
            self.watched_entry = 0.0
            self.initial_qty = 0.0
            self.base_qty = 0.0
            self.add_count = 0
            self.consumed_tp_levels = []
            self._tp_fill_dingtalk_levels = set()
            self.current_side = None
        if pending_tv_sl > 0:
            self._tv_stop_loss_ref = pending_tv_sl
            self._pending_open_tv_sl = pending_tv_sl
            if pending_hard > 0:
                self._tv_hard_sl_price = pending_hard
        recon = self._reconcile_live_vs_book(
            expect_flat=True, context="force_flat", notify_ok=False,
        )
        book_ok = bool(clean.get("ok"))
        recon_ok = bool(recon.get("ok", True))
        ok = book_ok and recon_ok
        book_txt = "清零✓" if book_ok else f"残留{clean.get('orders_after')}"
        recon_txt = "一致" if recon_ok else "异常"
        # 实盘清场核实后推送一次（开仓钉钉随后由 _open_position 再发）
        self._alert(
            "info" if ok else "warning",
            "FLIP_CLEAN",
            "先平后开：检测到已有持仓，已市价全平并撤单，准备执行新开仓"
            if ok
            else "先平后开·清场有残留",
            f"{reason} | 仓位归零✓ | 挂单{book_txt} | 对账{recon_txt}"
            + (f" | tv_sl@{pending_tv_sl:.2f}" if pending_tv_sl > 0 else ""),
            {
                "reason": reason,
                "clean": clean,
                "reconcile": recon,
                "exchange": self.exchange_id,
                "pending_tv_sl": pending_tv_sl,
            },
        )
        if not ok:
            return self._abort_force_flat(
                reason,
                fail_kind="仓位已平但挂单/对账未干净",
                detail={"clean": clean, "reconcile": recon},
            )
        return True


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

        return self._handle_tv_entry(
            action, curr_px, has_pos=has_pos, current_side=current_side,
        )

    def _close_then_open_entry(self, action: str, curr_px: float, ev) -> dict:
        """遗留同向换仓入口 → 统一走铁律先平后开（禁止与 _handle_tv_entry 双轨打架）。"""
        threshold = float(settings.SAME_DIR_IGNORE_PRICE_DIFF_PCT)
        reason = format_reopen_reason(ev, threshold)
        self._log("SIGNAL", f"⚡ 收到建仓信号 [{action}]，{reason} → 铁律先平后开")
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
            return {"status": "error", "reason": "flat_timeout", "message": "平仓未确认归零"}
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
        if float(getattr(self, "tv_sl", 0) or 0) > 0:
            shield = self._sync_tv_hard_stop(real_qty, force_replace=True)
            detail["tv_sl"] = self.tv_sl
            detail["shield"] = shield
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

    def _place_tv_entry_order(self, action: str, qty: float, limit_px: float) -> dict:
        """Checklist §2A: 市价开仓（数量已由 VPS 算仓确定）."""
        meta: dict = {
            "entry_order_style": "market",
            "limit_price": float(limit_px or 0),
            "qty": float(qty),
        }
        self.client.place_market_order(action, qty, self.symbol)
        return meta

    def _open_position(self, action: str, curr_px: float) -> dict:
        if hasattr(self, "_clear_trading_pause"):
            self._clear_trading_pause("new_open")
        self._pending_open_side = str(action or "").upper()
        leverage = self._bind_tv_leverage()
        self.client.cancel_all_open_orders(self.symbol)
        if hasattr(self, "_cancel_binance_all_close_stops"):
            purged = int(self._cancel_binance_all_close_stops() or 0)
            if purged:
                self._log("SIGNAL", f"🧹 开仓前清残留硬止损/条件单 ×{purged}")
        time.sleep(0.4)
        # 双保险：先平后开清场若仍抹掉 tv_sl，从硬止损缓存/本笔字段恢复后再算仓
        # Restore Pine stop_loss ref only (never VPS hang price into tv_sl).
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
                self._log("SIGNAL", f"开仓前恢复 TV stop_loss ref@{recovered:.4f}")
        qty, sizing_meta = self._resolve_entry_qty(curr_px)
        if qty <= 0:
            err = sizing_meta.get("error", "insufficient_balance")
            alert_type = (
                "NOTIONAL_CAP"
                if err in ("combined_notional_exceeded", "total_nominal_exceeded")
                else "INSUFFICIENT_BALANCE"
            )
            title = "总名义敞口超限" if alert_type == "NOTIONAL_CAP" else "开仓失败"
            unit = getattr(self, "qty_unit", "ETH")
            self._log("ERROR", f"开仓失败: {err} | meta={sizing_meta}")
            self._alert(
                "warning", alert_type, title,
                f"用户 {self.user_id} {getattr(self, 'canonical_symbol', '')} 无法开仓: {err} | "
                f"名义={sizing_meta.get('proposed_notional') or sizing_meta.get('order_amount')} "
                f"上限={sizing_meta.get('notional_cap')} ({sizing_meta.get('max_mult')}×本金) "
                f"unit={unit}",
                {
                    **sizing_meta,
                    "symbol": getattr(self, "canonical_symbol", None),
                    "qty_unit": unit,
                    "max_combined_mult": sizing_meta.get("max_mult"),
                },
            )
            return {
                "status": "error",
                "reason": err,
                "message": f"无法开仓（{err}）",
            }

        open_side = "BUY" if action == "LONG" else "SELL"
        entry_type = getattr(self, "_entry_type", "OPEN")
        unit = getattr(self, "qty_unit", "ETH")
        limit_px = float(
            getattr(self, "tv_price", 0)
            or curr_px
            or 0
        )
        self._log(
            "SIGNAL",
            f"🚀 [VPS开仓] {open_side} {qty} {unit} | {getattr(self, 'canonical_symbol', '')} "
            f"{entry_type} R{self.regime} | LIMIT@{limit_px:.4f}→IOC/市价补 | "
            f"名义{sizing_meta.get('order_amount')}U / sl_dist={sizing_meta.get('sl_distance')} "
            f"({sizing_meta.get('sizing_source')})",
        )
        entry_meta = self._place_tv_entry_order(action, qty, limit_px)
        sizing_meta["entry_order"] = entry_meta
        sizing_meta["order_qty"] = float(qty)
        time.sleep(1.2)

        pos = self.position_manager.get_position(self.symbol)
        if pos and float(pos.get("positionAmt", 0)) != 0:
            self.current_side = action
            real_qty = abs(float(pos["positionAmt"]))
            entry_price = float(pos["entryPrice"])
            # 开仓宽限：禁止立刻 CAP 市价减仓；trade_opened_at 先打点供 grace 判定
            self.trade_opened_at = time.time()
            self.base_qty = real_qty
            self.initial_qty = real_qty
            self.add_count = 0
            self.consumed_tp_levels = []
            self._tp_fill_dingtalk_levels = set()
            self.current_trade_id = self.on_trade_open(
                self.user_id, action, real_qty, entry_price, self.regime, self.tv_tps,
                symbol=self.canonical_symbol,
            )
            self.adopted_manual = False
            slip = (entry_price - self.tv_price) if action == "LONG" else (self.tv_price - entry_price)
            theme = resolve_exchange_theme(
                self.exchange_id, self.canonical_symbol, leverage=leverage,
            )
            detail = {
                "exchange": self.exchange_id,
                "symbol": self.canonical_symbol,
                "native_symbol": self.symbol,
                "qty_unit": self.qty_unit,
                "entry_type": entry_type,
                "regime": self.regime,
                "side": action,
                "qty": real_qty,
                "entry": entry_price,
                "tv_price": self.tv_price,
                "slippage": round(slip, 2),
                "tv_tps": list(self.tv_tps),
                "leverage": leverage,
                "atr": self.current_atr,
                **sizing_meta,
            }
            self._protect_and_monitor(real_qty, entry_price)
            protect = getattr(self, "_last_protect_result", None) or {}
            if protect.get("aborted"):
                self._log(
                    "ERROR",
                    "开仓后硬止损失败已撤仓·跳过OPEN钉钉",
                    protect,
                )
                return {
                    "status": "error",
                    "reason": "hard_sl_fail_abort",
                    "message": "硬止损挂单失败·已撤仓禁止裸奔",
                    "detail": protect,
                }
            defense = protect.get("defense") or getattr(self, "_last_defense_result", None) or {}
            if defense:
                detail["defense_matched"] = defense.get("matched")
                detail["defense_expected"] = defense.get("expected")
                detail["defense_summary"] = defense.get("summary")
            verify_note = ""
            if detail.get("defense_expected"):
                verify_note = (
                    f" | 实盘止盈 {detail.get('defense_matched')}/"
                    f"{detail.get('defense_expected')} 档"
                )
            shield = protect.get("shield") or getattr(self, "_last_shield_result", None) or {}
            sl_label = shield.get("label") or self._hard_stop_label()
            if shield.get("aligned") or shield.get("skipped") == "live_already_aligned":
                verify_note += f" | {sl_label}已核实 @{shield.get('stop_price', 0):.2f}"
            elif shield.get("armed") and shield.get("stop_price"):
                verify_note += f" | {sl_label} @{shield.get('stop_price', 0):.2f}"
            if float(getattr(self, "tv_sl", 0) or 0) > 0:
                detail["tv_sl"] = self.tv_sl
            vps_meta = getattr(self, "_vps_hard_sl_meta", None) or {}
            if vps_meta.get("hard_sl_pct_display"):
                detail["hard_sl_pct_display"] = vps_meta["hard_sl_pct_display"]
            if vps_meta.get("tv_sl_reference"):
                detail["tv_sl_reference"] = vps_meta["tv_sl_reference"]
            if shield:
                detail["shield"] = shield
                if shield.get("order_style"):
                    detail["hard_sl_order_style"] = shield["order_style"]
                if shield.get("limit_price"):
                    detail["hard_sl_limit_price"] = shield["limit_price"]
            slices = (
                self._expected_tp_levels(real_qty, entry_price)
                if hasattr(self, "_expected_tp_levels")
                else []
            )
            if slices:
                detail["tp_slices"] = slices
            detail["radar_armed"] = False
            detail["radar_active"] = False
            # Checklist §6 confirm mounts
            shield_ok = bool(
                shield.get("aligned")
                or shield.get("armed")
                or shield.get("skipped") == "live_already_aligned"
            )
            tp_ok = bool(
                defense.get("matched", 0) >= max(int(defense.get("expected", 0) or 0), 1)
                if defense.get("expected")
                else bool(slices)
            )
            detail["hard_sl_mounted"] = shield_ok
            detail["tp123_mounted"] = tp_ok
            detail["radar_standby"] = True
            detail["mount_confirm"] = {
                "hard_sl": "✅" if shield_ok else "❌",
                "tp123": "✅" if tp_ok else "❌",
                "radar": "✅",  # 候命（开仓时未激活，监控已启动）
            }
            from app.core.radar_trail import radar_effective_activation, regime_radar_activation
            detail["radar_activation"] = regime_radar_activation(int(self.regime or 3))
            tps = list(self.tv_tps or [])
            tp1_o = float(tps[0] or 0) if tps else 0.0
            detail["radar_activation_effective"] = radar_effective_activation(
                int(self.regime or 3),
                float(entry_price or 0),
                tp1_o,
                float(getattr(self, "current_atr", 0) or 0),
            )
            detail = enrich_tp_alert_detail(detail, regime=self.regime)
            enrich_suffix = ""
            enrich_note = getattr(self, "_last_enrich_note", "") or ""
            if enrich_note:
                enrich_suffix = f" | {enrich_note}"
            open_title = (
                f"{theme['accent']} GEMINI开仓 · {theme.get('symbol_label') or self.canonical_symbol} "
                f"· {theme['label']} 档位{self.regime} · {leverage}×"
            )
            self._log(
                "OPEN",
                f"🔶 战神出击：{self.canonical_symbol} {action} {real_qty} {unit} @ {entry_price} | 滑点 {slip:+.2f}{verify_note}{enrich_suffix}",
                detail,
            )
            self._alert(
                "info", "OPEN",
                open_title,
                f"{self.canonical_symbol} {action} {real_qty} {unit} @ {entry_price} | 滑点 {slip:+.2f} | "
                f"TV杠杆{leverage}× | 等效{detail.get('effective_leverage') or leverage}× | "
                f"TP {self.tv_tps} | ATR {self.current_atr}{verify_note}{enrich_suffix}",
                detail,
            )
            self._reconcile_live_vs_book(
                expect_side=action,
                expect_qty=real_qty,
                context="open",
                notify_ok=True,
            )
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
            return {
                "status": "ok",
                "action": action,
                "slippage": round(slip, 4),
                "trade_id": self.current_trade_id,
                "detail": detail,
            }
        if getattr(self, "_atr_fallback_pending_pause", False):
            # 降级已触发但开仓未成交：仍暂停，避免带着坏 ATR 连打
            self._atr_fallback_pending_pause = False
            if hasattr(self, "_pause_trading"):
                self._pause_trading(
                    "ATR应急降级后开仓未成交·已暂停待人工确认",
                    {"atr_fallback_detail": sizing_meta.get("atr_fallback_detail")},
                )
        last_err = ""
        if hasattr(self, "client"):
            last_err = str(getattr(self.client, "_last_market_order_error", "") or "")
        msg = "下单后未检测到持仓"
        if last_err:
            msg = f"市价开仓失败: {last_err}"
        elif float(qty or 0) > 0:
            msg = f"下单后未检测到持仓（已请求 qty={qty}）"
        self._log("ERROR", msg, {"order_qty": qty, "sizing": sizing_meta, "exchange_error": last_err})
        self._alert(
            "warning",
            "OPEN_FAILED",
            "开仓失败",
            msg,
            {
                "order_qty": float(qty or 0),
                "binding": sizing_meta.get("binding"),
                "final_qty": sizing_meta.get("final_qty"),
                "tv_qty_ignored_absurd": sizing_meta.get("tv_qty_ignored_absurd"),
                "exchange_error": last_err or None,
                "params": getattr(self.client, "_last_market_order_params", None)
                if hasattr(self, "client")
                else None,
            },
        )
        return {
            "status": "error",
            "reason": "open_failed",
            "message": msg,
            "order_qty": float(qty or 0),
            "sizing": {
                "binding": sizing_meta.get("binding"),
                "final_qty": sizing_meta.get("final_qty"),
                "tv_qty_ignored_absurd": sizing_meta.get("tv_qty_ignored_absurd"),
            },
            "exchange_error": last_err or None,
        }

    def _close_order_side(self) -> str:
        """Binance order side to flatten current position."""
        return "SELL" if self.current_side == "LONG" else "BUY"


    def _compute_tp_slices(
        self, qty: float, exclude_levels: set[int] | None = None
    ) -> list[tuple[int, float, float]]:
        """TP1/TP2 only. Prefer TV qty1/qty2 when present; else 30/30 of live qty."""
        from app.core.tp_regime_targets import PLACEABLE_TP_LEVELS

        exclude = set(exclude_levels or set())
        qty_f = float(qty or 0)
        tps = list(self.tv_tps or [])
        fields = getattr(self, "_tv_entry_fields", None) or {}
        tv_q1 = fields.get("tv_qty1")
        tv_q2 = fields.get("tv_qty2")

        # Absolute TV qty1/qty2 when both valid and sum ≤ live qty (+eps)
        if (
            tv_q1 is not None and tv_q2 is not None
            and float(tv_q1) > 0 and float(tv_q2) > 0
            and qty_f > 0
        ):
            q1 = self._round_qty(min(float(tv_q1), qty_f))
            rem = max(qty_f - q1, 0.0)
            q2 = self._round_qty(min(float(tv_q2), rem))
            out: list[tuple[int, float, float]] = []
            for level, part, px_i in ((1, q1, 0), (2, q2, 1)):
                if level in exclude or level not in PLACEABLE_TP_LEVELS:
                    continue
                px = float(tps[px_i]) if px_i < len(tps) else 0.0
                if part > 0 and px > 0:
                    out.append((level, part, px))
            if out:
                return out

        settings = dict(self.regime_settings)
        r = int(self.regime or 3)
        row = dict(settings.get(r) or settings.get(3) or {})
        row["ratios"] = [0.3, 0.3, 0.4]
        settings[r] = row
        slices = compute_tp_slices(
            qty_f,
            r,
            self.tv_tps,
            settings,
            exclude_levels=exclude | {3},
            round_qty_fn=self._round_qty,
            min_qty=float(getattr(self, "min_order_qty", 0) or 0),
        )
        return [(lv, q, px) for lv, q, px in slices if lv in PLACEABLE_TP_LEVELS]

    def _open_tp_prices_on_book(self) -> list[float]:
        prices: list[float] = []
        if hasattr(self, "_collect_tp_limit_orders"):
            for o in self._collect_tp_limit_orders():
                px = float(o.get("price", 0) or 0)
                if px > 0:
                    prices.append(round_price(px))
        elif hasattr(self.client, "get_open_orders"):
            for o in self.client.get_open_orders(self.symbol) or []:
                if str(o.get("type", "")).upper() != "LIMIT":
                    continue
                px = float(o.get("price", 0) or 0)
                if px > 0:
                    prices.append(round_price(px))
        return prices

    def _sync_consumed_tp_levels(self, live_qty: float, curr_px: float) -> list[int]:
        """Exchange-first: qty+book+price evidence merge (never mark TP1 on full open).

        Also mark contiguous tiers already past by mark/peak so restart never
        rehangs TP1 when price already through (only TP2/TP3 + radar).
        """
        from app.core.tp_slice_guard import compute_tp_slices, levels_past_by_mark

        anchor = float(self.initial_qty or live_qty)
        live = float(live_qty or 0)
        is_dc = self.exchange_id == "deepcoin"
        tol = tp_slice_qty_tolerance(anchor, is_contracts=is_dc)
        slices = compute_tp_slices(
            anchor, self.regime, self.tv_tps, self.regime_settings, exclude_levels=set(),
        )
        reduced = abs(anchor - live)
        tp1_slice = float(slices[0][1]) if slices else 0.0
        past_early = levels_past_by_mark(
            float(curr_px or 0),
            self.current_side,
            list(self.tv_tps or []),
            peak_px=float(getattr(self, "best_price", 0) or 0),
        )
        # 仅「真·误记账」才清 consumed：仓位仍满仓 + 现价未过 TP + 盘口上该档限价仍在。
        # 禁止在「TP 5min 超时撤单后 live==anchor」时清空 — 那会立刻触发核武重挂，
        # 与「超时移交·禁止重挂」铁律冲突，并在撤单滞后时叠出重复 TP。
        restore_tol = 1.0 if is_dc else 0.001
        if (
            tp1_slice > 0
            and abs(live - anchor) <= restore_tol
            and self.consumed_tp_levels
            and not past_early
        ):
            open_pxs = (
                self._open_tp_prices_on_book()
                if hasattr(self, "_open_tp_prices_on_book")
                else []
            )
            still_on_book = False
            for lvl in list(self.consumed_tp_levels or []):
                try:
                    idx = int(lvl) - 1
                    tp_px = float((self.tv_tps or [0, 0, 0])[idx] or 0) if idx >= 0 else 0.0
                except (TypeError, ValueError, IndexError):
                    tp_px = 0.0
                if tp_px > 0 and any(tp_price_matches(tp_px, p) for p in open_pxs):
                    still_on_book = True
                    break
            if still_on_book:
                logger.warning(
                    "[User %s] 仓位仍满且 TP 限价仍在盘口，清除误记账 consumed=%s",
                    self.user_id, self.consumed_tp_levels,
                )
                self.consumed_tp_levels = []
                if hasattr(self, "_tp_fill_dingtalk_levels"):
                    self._tp_fill_dingtalk_levels = set()
                if hasattr(self, "_save_state"):
                    self._save_state()
                return []
            logger.info(
                "[User %s] 满仓但 consumed=%s 且盘口无对应 TP → 保留记账"
                "（多为超时移交，禁止清掉后重挂）",
                self.user_id, self.consumed_tp_levels,
            )
        inferred = infer_filled_tp_levels(
            live,
            curr_px,
            self.current_side,
            initial_qty=anchor,
            consumed_tp_levels=self.consumed_tp_levels,
            regime=self.regime,
            tv_tps=self.tv_tps,
            regime_settings=self.regime_settings,
            open_tp_prices=self._open_tp_prices_on_book(),
            qty_tol=tol,
            is_contracts=is_dc,
            peak_px=float(getattr(self, "best_price", 0) or 0),
        )
        past = past_early
        # 只增不减：哨兵已确认的档位不被盘口延迟/短暂回挂抹掉
        prev = {int(x) for x in (self.consumed_tp_levels or []) if int(x) in (1, 2, 3)}
        merged = sorted(
            prev
            | {int(x) for x in inferred if int(x) in (1, 2, 3)}
            | {int(x) for x in past if int(x) in (1, 2, 3)}
        )
        if merged != sorted(self.consumed_tp_levels or []):
            logger.info(
                "[User %s] TP 已成交/已过价档位更新: %s → %s | 实盘 %s | 开仓锚 %s | 减仓 %.4f | past=%s",
                self.user_id, self.consumed_tp_levels, merged, live, anchor, reduced, sorted(past),
            )
        self.consumed_tp_levels = merged
        if hasattr(self, "_save_state"):
            self._save_state()
        return merged

    def _infer_filled_tp_levels(self, qty: float, curr_px: float) -> set[int]:
        """推断已成交 TP 档位（state 记录 + 开仓量对比 + 价格越过且无挂单）。"""
        from app.core.tp_slice_guard import levels_past_by_mark

        anchor = float(self.initial_qty or qty)
        tol = tp_slice_qty_tolerance(anchor, is_contracts=self.exchange_id == "deepcoin")
        filled = infer_filled_tp_levels(
            qty,
            curr_px,
            self.current_side,
            initial_qty=anchor,
            consumed_tp_levels=self.consumed_tp_levels,
            regime=self.regime,
            tv_tps=self.tv_tps,
            regime_settings=self.regime_settings,
            open_tp_prices=self._open_tp_prices_on_book(),
            qty_tol=tol,
            is_contracts=self.exchange_id == "deepcoin",
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
        open_prices = (
            self._open_tp_prices_on_book()
            if hasattr(self, "_open_tp_prices_on_book")
            else []
        )
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
                is_contracts=self.exchange_id == "deepcoin",
                peak_px=float(getattr(self, "best_price", 0) or 0),
            )
            if skip and reason in SKIP_REHANG_HARD:
                exclude.add(level)
        return exclude
    def _classify_qty_change(self, old_qty: float, new_qty: float, curr_px: float | None = None) -> str:
        from app.core.tp_slice_guard import compute_tp_slices, tp_limit_still_on_book

        tol = self._qty_match_tol(old_qty, new_qty)
        if new_qty <= 0:
            return "full_close"
        if new_qty > old_qty + tol:
            return "manual_add"
        reduced = old_qty - new_qty
        if reduced <= tol:
            return "unchanged"

        anchor = float(self.initial_qty or old_qty or 0)
        open_prices = (
            self._open_tp_prices_on_book()
            if hasattr(self, "_open_tp_prices_on_book")
            else []
        )
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
            is_contracts=self.exchange_id == "deepcoin",
            peak_px=float(getattr(self, "best_price", 0) or 0),
        )
        if level is not None:
            if level not in self.consumed_tp_levels:
                self.consumed_tp_levels.append(level)
            if hasattr(self, "_save_state"):
                self._save_state()
            self._notify_tp_fill_detected(level, old_qty, new_qty, px)
            return f"tp{level}_filled"

        # Aggressive sync (qty+book; price pullback OK)
        before = set(int(x) for x in (self.consumed_tp_levels or []))
        self._sync_consumed_tp_levels(new_qty, px if px > 0 else (self.client.get_current_price(self.symbol) or 0))
        after = set(int(x) for x in (self.consumed_tp_levels or []))
        gained = sorted(after - before)
        if gained:
            self._notify_tp_fill_detected(gained[0], old_qty, new_qty, px)
            return f"tp{gained[0]}_filled"

        # Heuristic: must also have price/peak at TP1 (forbid CAP/穿价秒平误报)
        if anchor > 0:
            from app.core.tp_slice_guard import price_reached_tp

            slices = compute_tp_slices(
                anchor, self.regime, self.tv_tps, self.regime_settings, exclude_levels=set(),
            )
            if slices:
                tp1_lvl, tp1_qty, tp1_px = slices[0]
                peak = float(getattr(self, "best_price", 0) or 0)
                px_ok = price_reached_tp(px, tp1_px, self.current_side) or (
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
                    self._notify_tp_fill_detected(1, old_qty, new_qty, px, heuristic=True)
                    return "tp1_filled"

        return "manual_reduce"

    def _notify_tp_fill_detected(
        self,
        level: int,
        old_qty: float,
        new_qty: float,
        curr_px: float,
        *,
        heuristic: bool = False,
    ) -> None:
        """VPS order monitor: TP1/TP2/TP3 fill → bump SL (1/2) + DingTalk."""
        lvl = int(level)
        alerted = getattr(self, "_tp_fill_dingtalk_levels", None)
        if alerted is None:
            self._tp_fill_dingtalk_levels = set()
            alerted = self._tp_fill_dingtalk_levels

        bump: dict = {}
        if lvl in (1, 2) and float(new_qty or 0) > 0 and hasattr(self, "_bump_sl_after_tp_reconcile"):
            try:
                bump = self._bump_sl_after_tp_reconcile(str(lvl)) or {}
            except Exception as exc:
                logger.warning("[User %s] TP%d SL bump failed: %s", self.user_id, lvl, exc)
                bump = {"error": str(exc)}
            if hasattr(self, "_boost_radar_after_tp_fill"):
                try:
                    self._boost_radar_after_tp_fill(f"tp{lvl}_filled", float(curr_px or 0), float(new_qty or 0))
                except Exception:
                    pass
        if hasattr(self, "_clear_defense_order_ids"):
            self._clear_defense_order_ids(str(lvl))
            if hasattr(self, "_save_state"):
                try:
                    self._save_state()
                except Exception:
                    pass

        detail = {
            "exchange": self.exchange_id,
            "level": lvl,
            "old_qty": float(old_qty),
            "new_qty": float(new_qty),
            "curr_px": float(curr_px or 0),
            "price": float(curr_px or 0),
            "qty": float(new_qty),
            "consumed_tp_levels": list(self.consumed_tp_levels or []),
            "tv_tps": list(self.tv_tps or []),
            "initial_qty": float(self.initial_qty or 0),
            "heuristic": heuristic,
            "side": self.current_side,
            "source": "vps_order_monitor",
            "sl_bump": bump,
            "current_sl": float(getattr(self, "current_sl", 0) or 0),
        }
        note = "（头寸推断）" if heuristic else ""
        self._log(
            "TP_FILLED",
            f"VPS监控·止盈TP{level}成交{note} {old_qty}→{new_qty} | SL@{detail['current_sl']}",
            detail,
        )
        if lvl in alerted:
            return
        alerted.add(lvl)
        if lvl == 1:
            title = "TP1 止盈成交"
            msg = (
                f"TP1 止盈成交，剩余仓位 70%，当前止损 "
                f"@{float(detail['current_sl'] or 0):.2f}"
            )
        elif lvl == 2:
            title = "TP2 止盈成交"
            msg = (
                f"TP2 止盈成交，剩余仓位 40%，当前止损 "
                f"@{float(detail['current_sl'] or 0):.2f}"
            )
        elif lvl == 3:
            # TP3 limit not placed — residual managed by breathing phase-2
            title = "止盈成交"
            msg = (
                f"{self.current_side} 成交价{curr_px or '—'} | "
                f"{old_qty}→{new_qty} | 阶段二由呼吸止损接管"
            )
            # Confirm flat → cancel residual orders + reset radar
            if float(new_qty or 0) <= float(getattr(self, "min_order_qty", 0) or 0) + 1e-12:
                if hasattr(self, "_purge_defense_orders_on_flat"):
                    try:
                        self._purge_defense_orders_on_flat("tp3_filled", notify=False)
                    except Exception:
                        pass
                if hasattr(self, "_reset_adverse_radar"):
                    try:
                        self._reset_adverse_radar(keep_tv_sl=False)
                    except Exception:
                        pass
                self.monitoring = False
        else:
            title = f"止盈TP{level}成交（VPS监控）{note}"
            msg = f"{self.current_side} {old_qty}→{new_qty} @ {curr_px or '—'} | 已成交档 {detail['consumed_tp_levels']}"
        self._alert("info", "TP_FILLED", title, msg, detail)

    def _reconcile_radar_context(self, recovery: dict | None) -> dict:
        """重启：开仓日志 + 最新 TV + DB 交易 三方核实雷达参数。"""
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
                self.initial_qty = max(float(self.initial_qty or 0), trade_qty)
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
            open_qty = float(open_log.get("qty") or 0)
            if open_qty > 0:
                self.initial_qty = max(float(self.initial_qty or 0), open_qty)
            if open_log.get("tv_tps"):
                self.tv_tps = normalize_tv_targets(open_log["tv_tps"])
            if open_log.get("regime"):
                self.regime = clamp_regime(open_log["regime"])
            if open_log.get("side"):
                self.last_tv_side = open_log["side"]
            if open_log.get("atr"):
                self.current_atr = float(open_log["atr"])

        tv_conflicts_state = False
        if latest_tv:
            report["sources"].append("latest_tv")
            report["latest_tv_action"] = latest_tv.get("action")
            report["latest_tv_at"] = latest_tv.get("created_at")
            tv_action = (latest_tv.get("action") or "").upper()
            state_tv = (recovery.get("state_last_tv_side") or "").upper()
            scope = (recovery.get("tv_signal_scope") or "").lower()
            tv_conflicts_state = (
                tv_action in ("LONG", "SHORT")
                and state_tv in ("LONG", "SHORT")
                and tv_action != state_tv
            )
            if tv_conflicts_state:
                report["warnings"].append("tv_direction_vs_state")
            if tv_action in ("LONG", "SHORT") and not tv_conflicts_state:
                self.last_tv_side = tv_action
                if any(latest_tv.get("tv_tps") or []):
                    self.tv_tps = normalize_tv_targets(latest_tv["tv_tps"])
                if latest_tv.get("regime"):
                    self.regime = clamp_regime(latest_tv["regime"])
                if latest_tv.get("atr"):
                    self.current_atr = float(latest_tv["atr"])
                if latest_tv.get("price"):
                    self.tv_price = round_price(latest_tv["price"])
            elif tv_action in ("LONG", "SHORT") and tv_conflicts_state:
                if state_tv in ("LONG", "SHORT"):
                    self.last_tv_side = state_tv
                report["warnings"].append(
                    "ignored_conflicting_tv_for_state"
                    if scope == "platform_fallback"
                    else "ignored_conflicting_user_tv_for_state"
                )
            elif tv_action.startswith("CLOSE"):
                report["warnings"].append("tv_close_while_position")
                report["latest_tv_action"] = tv_action
                if entry_tv and (entry_tv.get("action") or "").upper() in ("LONG", "SHORT"):
                    report["latest_entry_tv_action"] = entry_tv.get("action")
                    if not tv_conflicts_state:
                        self.last_tv_side = (entry_tv.get("action") or "").upper()

        elif entry_tv:
            report["sources"].append("latest_entry_tv")
            entry_action = (entry_tv.get("action") or "").upper()
            report["latest_entry_tv_action"] = entry_action
            if entry_action in ("LONG", "SHORT") and not self.last_tv_side:
                self.last_tv_side = entry_action

        if tv_conflicts_state:
            pass  # tv_sl recomputed in finalize_recovery_tv_params
        else:
            pass

        finalize_recovery_tv_params(self, report, recovery)

        report["last_tv_side"] = self.last_tv_side
        report["tv_tps"] = list(self.tv_tps)
        report["regime"] = self.regime
        if open_log.get("side"):
            self._open_log_side = open_log.get("side")
        return report

    def _price_matches(self, a: float, b: float) -> bool:
        return abs(round_price(a) - round_price(b)) < MIN_SL_MOVE

    def _qty_matches(self, a: float, b: float, anchor: float | None = None) -> bool:
        anchor = anchor if anchor is not None else max(abs(float(a)), abs(float(b)), 1e-9)
        tol = qty_drift_tolerance(a, b)
        return abs(round_quantity(a) - round_quantity(b)) <= tol + 1e-9

    def _is_reduce_only_tp_limit(self, order: dict, close_side: str) -> bool:
        if (order.get("type") or "").upper() != "LIMIT":
            return False
        if order.get("side") != close_side:
            return False
        val = order.get("reduceOnly")
        if val is True or str(val).lower() in ("true", "1"):
            return True
        px = round_price(order.get("price", 0))
        if px <= 0:
            return False
        return any(tp_price_matches(px, t) for t in self.tv_tps if t > 0)

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
        """Deprecated direct place — route through breathing engine only."""
        stop_price = round_price(stop_price)
        live_qty = float(getattr(self, "watched_qty", 0) or 0)
        if live_qty <= 0 and hasattr(self, "_resolve_adverse_live_qty"):
            try:
                live_qty = float(self._resolve_adverse_live_qty(0) or 0)
            except Exception:
                live_qty = 0.0
        self.current_sl = float(stop_price)
        if hasattr(self, "_sync_tv_hard_stop") and live_qty > 0:
            shield = self._sync_tv_hard_stop(live_qty, force_replace=True) or {}
            ok = bool(shield.get("aligned") or shield.get("armed") or shield.get("ok"))
            return {
                "ok": ok,
                "label": "SL",
                "order_id": shield.get("order_id"),
                "stop_price": stop_price,
                "via": "breathing_engine",
                "shield": shield,
            }
        # Fallback only if breath path unavailable
        last_err = None
        for attempt in range(1, TP_RETRY_MAX + 1):
            order = self.client.place_stop_market_order(
                close_side, stop_price, self.symbol,
                quantity=live_qty if live_qty > 0 else None,
            )
            if order:
                return {
                    "ok": True,
                    "label": "SL",
                    "order_id": order.get("orderId"),
                    "stop_price": stop_price,
                    "attempt": attempt,
                    "via": "legacy_fallback",
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
            if otype == "LIMIT" and self._is_reduce_only_tp_limit(o, close_side):
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
            tracked_oid = None
            if hasattr(self, "_defense_order_id"):
                tracked_oid = self._defense_order_id(str(level))
            by_id = []
            if tracked_oid is not None:
                by_id = [
                    lo for lo in live_limits
                    if lo.get("order_id") is not None
                    and str(lo.get("order_id")) == str(tracked_oid)
                ]
            at_price = [
                lo for lo in live_limits
                if self._price_matches(lo["price"], price)
            ]
            # Prefer exact order-id match when persisted (checklist 4.3)
            candidates = by_id if by_id else at_price
            if len(candidates) > 1 and not by_id:
                duplicate_tps.append({
                    "level": level,
                    "price": round_price(price),
                    "expected_qty": qty,
                    "orders": candidates,
                })
            elif len(candidates) == 1:
                live = candidates[0]
                if self._qty_matches(live["qty"], qty, anchor=qty):
                    matched_tps.append({"level": level, **live})
                    if hasattr(self, "_remember_defense_order_id") and live.get("order_id"):
                        self._remember_defense_order_id(str(level), live["order_id"])
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
                if tracked_oid is not None and hasattr(self, "_clear_defense_order_ids"):
                    # Tracked id gone from open book — clear stale id (fill or cancel)
                    self._clear_defense_order_ids(str(level))

        sl_live = live_stops[0] if live_stops else None
        tracked_sl = self._defense_order_id("sl") if hasattr(self, "_defense_order_id") else None
        if tracked_sl is not None:
            for s in live_stops:
                if str(s.get("order_id")) == str(tracked_sl):
                    sl_live = s
                    break
            else:
                if hasattr(self, "_clear_defense_order_ids"):
                    self._clear_defense_order_ids("sl")
        elif sl_live and hasattr(self, "_remember_defense_order_id") and sl_live.get("order_id"):
            self._remember_defense_order_id("sl", sl_live["order_id"])

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
        consumed = sorted(set(getattr(self, "consumed_tp_levels", []) or []))
        if consumed:
            remaining = [s for s in slices if s[0] not in consumed]
            rem_qty = round_quantity(sum(q for _, q, _ in remaining))
            parts.append(
                f"已成交TP{''.join(str(x) for x in consumed)}"
                f" → 剩余{len(remaining)}档/{rem_qty}ETH"
            )
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
        from app.core.tp_slice_guard import sanitize_tp_limit_price, should_skip_rehang_tp_level

        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        placed: list = []
        failed: list = []
        mark = 0.0
        try:
            mark = float(self.client.get_current_price(self.symbol) or 0)
        except Exception:
            mark = 0.0
        open_prices = (
            self._open_tp_prices_on_book()
            if hasattr(self, "_open_tp_prices_on_book")
            else []
        )
        consumed = {int(x) for x in (self.consumed_tp_levels or []) if int(x) in (1, 2, 3)}
        live_qty = float(getattr(self, "watched_qty", 0) or getattr(self, "initial_qty", 0) or 0)
        for level, qty, price in slices:
            if qty <= 0 or price <= 0:
                continue
            skip, skip_reason = should_skip_rehang_tp_level(
                int(level),
                float(price),
                side=self.current_side,
                curr_px=mark,
                consumed=consumed,
                live_qty=live_qty,
                initial_qty=float(self.initial_qty or live_qty),
                regime=int(self.regime or 3),
                tv_tps=list(self.tv_tps or []),
                regime_settings=self.regime_settings,
                open_tp_prices=open_prices,
                is_contracts=self.exchange_id == "deepcoin",
                peak_px=float(getattr(self, "best_price", 0) or 0),
            )
            place_px = float(price)
            if skip and skip_reason in ("consumed", "price_book_filled", "qty_book_implies_filled", "price_past_tp"):
                self._log("TP_SKIP_REHANG", f"全量重挂跳过 TP{level}: {skip_reason}")
                if int(level) and int(level) not in consumed and skip_reason != "consumed":
                    consumed.add(int(level))
                    self.consumed_tp_levels = sorted(consumed)
                    if hasattr(self, "_save_state"):
                        self._save_state()
                continue
            if skip and skip_reason == "no_mark_price":
                failed.append({"ok": False, "label": f"TP{level}", "reason": "no_mark_price"})
                continue
            from app.core.tp_slice_guard import tp_would_instant_fill
            # 现价已过 → 禁止推离补挂（防 TP1 死亡螺旋）
            if tp_would_instant_fill(self.current_side, place_px, mark):
                self._log("TP_SKIP_REHANG", f"全量重挂跳过 TP{level}: mark_past")
                if int(level) and int(level) not in consumed:
                    consumed.add(int(level))
                    self.consumed_tp_levels = sorted(consumed)
                    if hasattr(self, "_save_state"):
                        self._save_state()
                continue
            # 穿价 → 拒绝挂出（不再 push-and-place）
            place_px, adj = sanitize_tp_limit_price(self.current_side, place_px, mark)
            if place_px <= 0 or adj.startswith("pushed"):
                self._log("TP_SKIP_REHANG", f"全量重挂跳过 TP{level}: {adj or 'unsafe'}")
                if int(level) and int(level) not in consumed:
                    consumed.add(int(level))
                    self.consumed_tp_levels = sorted(consumed)
                    if hasattr(self, "_save_state"):
                        self._save_state()
                continue
            result = self._place_limit_with_retry(close_side, qty, place_px, f"TP{level}")
            if result["ok"]:
                placed.append(result)
                if hasattr(self, "_mark_tp_placed"):
                    self._mark_tp_placed(int(level), order_id=result.get("order_id"))
                if hasattr(self, "_save_state"):
                    self._save_state()
            else:
                failed.append(result)
        if dynamic_sl and dynamic_sl > 0:
            sl_result = self._place_stop_with_retry(close_side, dynamic_sl)
            if sl_result["ok"]:
                placed.append(sl_result)
                if hasattr(self, "_remember_defense_order_id"):
                    self._remember_defense_order_id("sl", sl_result.get("order_id"))
                if hasattr(self, "_save_state"):
                    self._save_state()
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
        智能撤销重挂：重复/缺失/比例错 → 只撤 TP 限价 → 按当前头寸重挂 TP。
        绝不 cancel_all（禁止误撤呼吸止损条件槽）。
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

        # Route A：只撤 TP 限价，保留硬止损/雷达条件槽
        if hasattr(self, "_cancel_all_tp_limit_orders"):
            purged = int(self._cancel_all_tp_limit_orders() or 0)
            cancel_result = {"ok": True, "mode": "tp_only", "purged": purged}
        else:
            cancel_result = self._cancel_all_verified()
        placed: list = []
        failed: list = []
        post = scan

        for attempt in range(HEAL_PLACE_ROUNDS):
            # 重挂仅 TP；dynamic_sl 不在此槽挂（雷达另走 _ensure_radar_sl）
            placed, failed = self._place_all_defense_orders(slices, dynamic_sl=None)
            time.sleep(0.5)
            post = self._scan_open_defenses(slices, dynamic_sl=None)
            if post.get("aligned") and not failed:
                break

        # 雷达另槽补挂；硬止损若被旧路径误撤则补回（只补缺失）
        if dynamic_sl and hasattr(self, "_ensure_radar_sl"):
            try:
                self._ensure_radar_sl(dynamic_sl, qty)
            except Exception as e:
                logger.warning("[User %s] heal radar rehang: %s", self.user_id, e)
        if float(getattr(self, "tv_sl", 0) or 0) > 0 and hasattr(self, "_sync_tv_hard_stop"):
            try:
                self._sync_tv_hard_stop(qty, force_replace=False)
            except Exception as e:
                logger.warning("[User %s] heal hard-SL rehang: %s", self.user_id, e)

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
            level = int(item.get("level") or 0)
            tp_px = float(item.get("price") or 0)
            mark = 0.0
            try:
                mark = float(self.client.get_current_price(self.symbol) or 0)
            except Exception:
                mark = 0.0
            from app.core.tp_slice_guard import (
                should_skip_rehang_tp_level,
                tp_would_instant_fill,
                SKIP_REHANG_PERSIST_CONSUMED,
            )
            open_prices = (
                self._open_tp_prices_on_book()
                if hasattr(self, "_open_tp_prices_on_book")
                else []
            )
            consumed = {int(x) for x in (self.consumed_tp_levels or []) if int(x) in (1, 2, 3)}
            skip, skip_reason = should_skip_rehang_tp_level(
                level,
                tp_px,
                side=self.current_side,
                curr_px=mark,
                consumed=consumed,
                live_qty=float(qty or 0),
                initial_qty=float(self.initial_qty or qty or 0),
                regime=int(self.regime or 3),
                tv_tps=list(self.tv_tps or []),
                regime_settings=self.regime_settings,
                open_tp_prices=open_prices,
                is_contracts=self.exchange_id == "deepcoin",
                peak_px=float(getattr(self, "best_price", 0) or 0),
            )
            if skip or tp_would_instant_fill(self.current_side, tp_px, mark):
                reason = skip_reason or "mark_past"
                self._log("TP_SKIP_REHANG", f"缺失补挂跳过 {label}: {reason}")
                if level and level not in consumed and reason in SKIP_REHANG_PERSIST_CONSUMED | {"mark_past"}:
                    consumed.add(level)
                    self.consumed_tp_levels = sorted(consumed)
                    if hasattr(self, "_save_state"):
                        self._save_state()
                continue
            result = self._place_limit_with_retry(
                close_side, item["qty"], item["price"], label
            )
            if result["ok"]:
                repaired.append(result)
                if hasattr(self, "_mark_tp_placed"):
                    self._mark_tp_placed(int(level), order_id=result.get("order_id"))
                if hasattr(self, "_save_state"):
                    self._save_state()
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
                if hasattr(self, "_remember_defense_order_id"):
                    self._remember_defense_order_id("sl", sl_result.get("order_id"))
                if hasattr(self, "_save_state"):
                    self._save_state()
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
            curr_px = self.client.get_current_price(self.symbol)
            exclude = self._active_tp_exclude_levels(qty, curr_px)
            slices = self._compute_tp_slices(qty, exclude_levels=exclude)
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

        if scan.get("duplicate_tps"):
            purged = self._purge_duplicate_tp_orders(qty)
            if purged:
                time.sleep(0.4)
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

    def _protect_and_monitor(self, qty: float, entry_price: float) -> dict:
        """
        开仓后一次性挂好 TP1+TP2 + 呼吸止损；实盘核实后由 _open_position 推钉钉。
        返回 {ok, aborted, defense, shield}；硬止损挂失败则撤仓并 aborted=True（禁止裸奔）。
        """
        self._reset_adverse_radar(keep_tv_sl=False)
        seed_stop = float(getattr(self, "_sizing_initial_stop", 0) or 0)
        self._init_breathing_on_open(
            entry_price,
            atr=float(
                getattr(self, "_tv_atr_ref", 0)
                or getattr(self, "initial_atr", 0)
                or getattr(self, "current_atr", 0)
                or 0
            ),
        )
        # Prefer sizing-time initialStop if ATR refresh drifted slightly
        if seed_stop > 0 and float(getattr(self, "initial_stop", 0) or 0) > 0:
            # Keep engine stop from init; sizing already used same ATR formula
            pass
        self.best_price = entry_price
        self.watched_qty = qty
        self.watched_entry = entry_price
        self.monitoring = True
        self._ensure_price_ws()
        result: dict = {}
        shield: dict = {}
        pos = self._get_active_position()
        if pos:
            if hasattr(self, "_cancel_binance_all_close_stops"):
                self._cancel_binance_all_close_stops()
            # ① 只挂 TP123 限价（不碰硬止损/雷达槽）
            result = self._smart_realign_defenses(
                pos["size"],
                pos["entry_price"],
                dynamic_sl=None,
                reason="开仓后智能防线对齐·仅TP123",
            )
            # 一次补挂：若未齐再核武一轮（仍只动 TP）
            if (
                result.get("expected", 0) > 0
                and result.get("matched", 0) < result.get("expected", 0)
                and hasattr(self, "_nuclear_realign_tp")
            ):
                self._log(
                    "DEFENSE",
                    f"开仓TP未齐 {result.get('matched')}/{result.get('expected')} → 再补挂一轮",
                )
                self._defense_open_init_logs = True
                try:
                    audit = self._nuclear_realign_tp(
                        pos["size"], pos["entry_price"], dynamic_sl=None, rounds=2,
                    )
                finally:
                    self._defense_open_init_logs = False
                result = {
                    **result,
                    "matched": audit.get("matched_full", result.get("matched")),
                    "expected": audit.get("expected", result.get("expected")),
                    "audit": audit,
                    "nuclear_retry": True,
                    "summary": self._format_audit_summary(audit),
                }
            self._last_defense_result = result
            summary = self._format_audit_summary(result.get("audit") or {})
            self._log(
                "DEFENSE",
                f"🛡️ 开仓防线核查 {result.get('matched')}/{result.get('expected')} | {summary}",
                result,
            )
            if result.get("expected", 0) > 0 and result.get("matched", 0) < result.get("expected", 0):
                self._alert(
                    "warning",
                    "DEFENSE",
                    "开仓后限价止盈未全部挂上",
                    f"{self.current_side} {pos['size']} {getattr(self, 'qty_unit', 'ETH')} | "
                    f"仅 {result.get('matched')}/{result.get('expected')} 档 | {summary}",
                    result,
                )
            # ② 呼吸止损挂一次
            shield = self._sync_tv_hard_stop(pos["size"], at_open=True, force_replace=True)
            self._last_shield_result = shield
            sl_label = shield.get("label") or self._hard_stop_label()
            shield_note = ""
            if shield.get("aligned") or shield.get("skipped") == "live_already_aligned":
                shield_note = f" | {sl_label}已核实 @{shield.get('stop_price', 0):.2f}"
            elif shield.get("armed"):
                shield_note = f" | {sl_label} @{shield.get('stop_price', 0):.2f}"
            breath_sl = float(
                getattr(self, "current_sl", 0)
                or getattr(self, "initial_stop", 0)
                or getattr(self, "tv_sl", 0)
                or 0
            )
            if shield.get("placed", 0) > 0:
                self._log(
                    "BREATH_STEP",
                    f"🛡️ 开仓 {sl_label}已挂 @{shield.get('stop_price', 0):.2f}{shield_note}",
                    shield,
                )
            elif shield.get("aligned") or shield.get("skipped") == "live_already_aligned":
                self._log(
                    "BREATH_STEP",
                    f"🛡️ 开仓 {sl_label}实盘已存在 @{shield.get('stop_price', 0):.2f}",
                    shield,
                )
            elif breath_sl > 0:
                self._alert(
                    "critical",
                    "ADVERSE_SL",
                    "开仓后硬止损未挂上·立即撤仓",
                    f"{self.current_side} {pos['size']} | {sl_label} @{breath_sl:.2f} | {shield}",
                    shield,
                )
                # 硬止损挂单失败 → 立即平仓，禁止裸奔
                try:
                    self._close_all(
                        "硬止损挂单失败·禁止裸奔",
                        close_action="HARD_SL_FAIL_ABORT",
                        close_trigger="hard_sl_place_failed",
                    )
                except Exception as e:
                    logger.error(
                        "[User %s] hard-SL fail abort close error: %s",
                        getattr(self, "user_id", "?"),
                        e,
                    )
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
        self._save_state()
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
        """Keep markPrice WS alive and bind radar to every tick (fastest path)."""
        if hasattr(self.client, "start_public_price_ws"):
            self.client.start_public_price_ws(self.symbol)
        if hasattr(self.client, "register_price_listener") and not self._radar_ws_bound:
            self.client.register_price_listener(self._on_ws_price_tick)
            self._radar_ws_bound = True

    def _unbind_price_ws_listener(self) -> None:
        if self._radar_ws_bound and hasattr(self.client, "unregister_price_listener"):
            try:
                self.client.unregister_price_listener(self._on_ws_price_tick)
            except Exception:
                pass
        self._radar_ws_bound = False

    def _on_ws_price_tick(self, symbol: str, price: float) -> None:
        """WebSocket mark push → immediate TP1-path / trail evaluate (throttled)."""
        if not self.monitoring or float(price or 0) <= 0:
            return
        want = str(getattr(self, "symbol", "") or "").upper()
        got = str(symbol or "").upper()
        if want and got and want != got:
            # ETHUSDT vs ETH-USDT-SWAP / ETH_USDT
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

    def _radar_ws_fast_tick(self, curr_px: float) -> None:
        """
        Lightweight WS-driven radar: sync TP fills + arm/trail on remaining qty.
        Skips CAP/heavy heal — sentinel still does those on slower cadence.
        """
        if curr_px <= 0 or not self.monitoring:
            return
        pos = self._get_active_position()
        if not pos or float(pos.get("size") or 0) <= 0:
            return
        live_qty = float(pos["size"])
        entry = float(pos.get("entry_price") or self.watched_entry or 0)
        if self.current_side == "LONG":
            self.best_price = max(float(self.best_price or entry or 0), curr_px)
        elif self.current_side == "SHORT":
            bp = float(self.best_price or entry or 0)
            self.best_price = min(bp, curr_px) if bp > 0 else curr_px
        if hasattr(self, "_sync_consumed_tp_levels"):
            before = set(int(x) for x in (self.consumed_tp_levels or []))
            self._sync_consumed_tp_levels(live_qty, curr_px)
            after = set(int(x) for x in (self.consumed_tp_levels or []))
            gained = sorted(after - before)
            if gained and hasattr(self, "_notify_tp_fill_detected"):
                self._notify_tp_fill_detected(gained[0], self.watched_qty or live_qty, live_qty, curr_px)
                if hasattr(self, "_boost_radar_after_tp_fill"):
                    self._boost_radar_after_tp_fill(f"tp{gained[0]}_filled", curr_px, live_qty)
        self.watched_qty = live_qty
        if entry > 0:
            self.watched_entry = entry
        if hasattr(self, "_orchestrate_defense_monitoring"):
            self._orchestrate_defense_monitoring(live_qty, curr_px)

    def _handle_position_query_failure(self, err: Exception) -> None:
        """API failure: keep book, pause flat/auto judgment for this symbol."""
        from datetime import datetime, timezone
        from app.core.exchange_errors import ExchangeTransientError

        already = bool(getattr(self, "_position_query_degraded", False))
        self._position_query_degraded = True
        self._position_query_error = str(err)[:500]
        ban_ms = getattr(err, "banned_until_ms", None) if isinstance(err, ExchangeTransientError) else None
        if ban_ms:
            self._position_query_ban_until_ms = int(ban_ms)
        detail = {
            "exchange": getattr(self, "exchange_id", None),
            "symbol": getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None),
            "error": str(err)[:400],
            "watched_qty": float(getattr(self, "watched_qty", 0) or 0),
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
            "[User %s] position query failed — keep book qty=%s side=%s | %s",
            self.user_id,
            detail["watched_qty"],
            detail["current_side"],
            err,
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

    def _clear_position_query_degraded(self) -> None:
        if not getattr(self, "_position_query_degraded", False):
            return
        self._position_query_degraded = False
        self._position_query_error = ""
        self._position_query_ban_until_ms = None
        logger.info(
            "[User %s] position query recovered — auto flat judgment resumed",
            self.user_id,
        )
        if hasattr(self, "_alert"):
            self._alert(
                "info",
                "EXCHANGE_QUERY_OK",
                "交易所仓位查询已恢复",
                "自动空仓/对账判断已恢复",
                {
                    "exchange": getattr(self, "exchange_id", None),
                    "symbol": getattr(self, "canonical_symbol", None) or getattr(self, "symbol", None),
                },
            )

    def _get_active_position(self) -> dict | None:
        """Confirmed live position, or None if exchange reports flat.

        Raises ExchangeTransientError on API failure — never invents flat.
        """
        from app.core.exchange_errors import ExchangeTransientError

        try:
            pos = self.position_manager.get_position(self.symbol)
        except ExchangeTransientError as e:
            self._handle_position_query_failure(e)
            raise
        self._clear_position_query_degraded()
        if not pos or float(pos.get("positionAmt", 0)) == 0:
            return None
        amt = float(pos["positionAmt"])
        return {
            "size": abs(amt),
            "entry_price": float(pos.get("entryPrice", 0)),
            "side": "LONG" if amt > 0 else "SHORT",
        }

    def _wait_until_flat(self, timeout: float = FLAT_WAIT_TIMEOUT, poll: float = FLAT_WAIT_POLL) -> bool:
        """确认交易所持仓归零后再新开，避免残仓叠加。查询失败视为未确认空仓。"""
        from app.core.exchange_errors import ExchangeTransientError

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                pos = self._get_active_position()
            except ExchangeTransientError:
                time.sleep(poll)
                continue
            if not pos or pos["size"] <= 0:
                return True
            time.sleep(poll)
        try:
            pos = self._get_active_position()
        except ExchangeTransientError:
            return False
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
            from app.services.radar_context import get_latest_tv_signal_for_user

            db = SessionLocal()
            try:
                tv = get_latest_tv_signal_for_user(db, self.user_id)
                if not tv:
                    from app.services.radar_context import get_latest_tv_signal
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
            radar_active=bool(
                getattr(self, "radar_activated", False)
                or getattr(self, "radar_latched", False)
                or (hasattr(self, "_is_radar_active") and self._is_radar_active())
            ),
            current_sl=float(self.current_sl or 0),
            initial_stop=float(
                getattr(self, "tv_sl", 0)
                or getattr(self, "_tv_hard_sl_price", 0)
                or 0
            ),
            platform_initiated_market=platform_market,
            peak_price=float(getattr(self, "best_price", 0) or 0),
            exit_price=0.0,
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
        tv_reason: str | None = None,
        tv_close_ctx: dict | None = None,
        alert_sev: str = "info",
        extra_detail: dict | None = None,
    ) -> None:
        if not self.current_trade_id:
            return
        pnl = 0.0
        live_pnl_pct = None
        pnl_source = "mark_estimate"
        if self.watched_entry and exit_price:
            diff = exit_price - self.watched_entry
            if self.current_side == "SHORT":
                diff = -diff
            pnl = diff * float(self.watched_qty or 0)
            if self.watched_entry > 0:
                live_pnl_pct = round(diff / self.watched_entry * 100, 2)

        start_ms = int(self.trade_opened_at * 1000) if self.trade_opened_at else None
        # Prefer exchange fill realized PnL (ETH contract) when available.
        try:
            from app.services.exchange_fill_sync import fetch_live_eth_fills, sum_realized_from_fills
            fills = fetch_live_eth_fills(
                self.client, getattr(self, "exchange_id", "binance"), start_time_ms=start_ms,
            )
            fill_pnl = sum_realized_from_fills(fills, start_ms=start_ms)
            if fills:
                pnl = float(fill_pnl)
                pnl_source = "exchange_fills"
        except Exception as exc:
            logging.getLogger(__name__).warning("close fill pnl lookup failed: %s", exc)

        funding_fee = self.client.get_funding_fees(self.symbol, start_ms)
        display_reason = tv_reason or reason
        verify_note = build_verify_note(
            exit_price=exit_price,
            live_pnl_pct=live_pnl_pct,
            tv_pnl_pct=tv_pnl_pct,
            flat_confirmed=True,
        )
        close_detail = build_close_detail(
            exchange_id=self.exchange_id,
            side=self.current_side,
            qty=float(self.watched_qty or 0),
            entry=float(self.watched_entry or 0),
            regime=self.regime,
            atr=self.current_atr,
            exit_price=exit_price,
            pnl=pnl,
            funding_fee=funding_fee,
            tv_fields=tv_close_ctx,
            close_action=close_action,
            tv_reason=display_reason,
            live_pnl_pct=live_pnl_pct,
            verify_note=verify_note,
            attribution=attribution,
            trade_id=self.current_trade_id,
        )
        if extra_detail:
            close_detail.update(extra_detail)
        close_detail["pnl_source"] = pnl_source
        if tv_side:
            close_detail["tv_side"] = tv_side
        if tv_pnl_pct is not None:
            close_detail["tv_pnl_pct"] = round(float(tv_pnl_pct), 2)
        if tv_side and self.current_side and tv_side != self.current_side:
            close_detail["tv_side_mismatch"] = True
            self._log(
                "WARN",
                f"TV 方向 {tv_side} 与实盘 {self.current_side} 不一致（仍按实盘全平）",
                {"tv_side": tv_side, "live_side": self.current_side, "close_action": close_action},
            )

        self.on_trade_close(self.current_trade_id, exit_price, pnl, display_reason, funding_fee)
        self._log("CLOSE", display_reason, close_detail)
        alert_type = resolve_close_alert_type(close_action, display_reason, attribution)
        alert_title = resolve_close_alert_title(close_action, display_reason, attribution)
        ding_head = display_reason
        if attribution and not close_action:
            ding_head = attribution.get("human_reason") or display_reason
        ding_msg = format_close_dingtalk_message(ding_head, verify_note)
        self._alert(alert_sev, alert_type, alert_title, ding_msg, close_detail)
        if attribution and attribution.get("anomaly"):
            self._alert(
                "warning",
                "CLOSE_ANOMALY",
                "平仓原因待核实",
                attribution.get("human_reason") or display_reason,
                attribution,
            )

    def _handle_detected_flat(
        self, trigger: str = "sentinel_zero", *, skip_eager_purge: bool = False,
    ) -> bool:
        """Confirm flat, attribute cause, book-close, and detect false-flat / sync issues."""
        if not skip_eager_purge:
            self._purge_defense_orders_on_flat(trigger, notify=False)

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

    def _handle_manual_flat_detected(self, reason: str) -> None:
        """账本有仓、实盘已平：立即撤 TP123 并收口账本."""
        logger.info("[User %s] manual flat detected: %s", self.user_id, reason)
        self._purge_defense_orders_on_flat("manual_flat", notify=True)
        self._handle_detected_flat("manual_flat", skip_eager_purge=True)

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
        if hasattr(self, "_clear_position_local_state"):
            self._clear_position_local_state()
        else:
            self.watched_qty = 0.0
            self.watched_entry = 0.0
            self.initial_qty = 0.0
            self.base_qty = 0.0
            self.add_count = 0
            self.current_side = None
            self.best_price = 0.0
            self.consumed_tp_levels = []
            self._tp_fill_dingtalk_levels = set()
            self.current_trade_id = None
            self.trade_opened_at = None
        self._save_state()
        self._purge_defense_orders_on_flat("dust_sweep", notify=True)

    def _scan_and_sweep_dust_on_startup(self) -> bool:
        pos = self._get_active_position()
        if not pos or pos["size"] <= 0:
            return False
        if not self.current_side:
            self.current_side = pos["side"]
        if not self._is_dust_qty(pos["size"]):
            return False
        reason = (
            "仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)"
            if (self.initial_qty > 0 or self.watched_qty > 0)
            else "重启扫描：盘口蚂蚁仓自动扫平"
        )
        self._sweep_dust_and_finalize(reason)
        return True

    def _recover_missed_flat_on_startup(self, was_monitoring: bool = False) -> bool:
        from app.core.exchange_errors import ExchangeTransientError

        try:
            pos = self._get_active_position()
        except ExchangeTransientError:
            logger.error(
                "[User %s] skip flat reconcile on startup — position query unavailable "
                "(keeping last-known book)",
                self.user_id,
            )
            return False
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
        self._purge_defense_orders_on_flat("startup_reconcile", notify=True)
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
        if hasattr(self, "_clear_position_local_state"):
            self._clear_position_local_state()
        else:
            self.watched_qty = 0.0
            self.watched_entry = 0.0
            self.initial_qty = 0.0
            self.base_qty = 0.0
            self.add_count = 0
            self.current_side = None
            self.best_price = 0.0
            self.consumed_tp_levels = []
            self.current_trade_id = None
            self.trade_opened_at = None
        self._save_state()
        return True

    def _start_idle_flat_patrol(self) -> None:
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
                except Exception as exc:
                    logger.error(f"[User {self.user_id}] idle patrol: {exc}")
                finally:
                    self._lock.release()

        threading.Thread(target=loop, daemon=True, name=f"idle-patrol-u{self.user_id}").start()

    def _refresh_radar_state_on_recover(self, curr_px: float, entry: float) -> None:
        """Restart: restore breathing stop (compat name kept for call sites)."""
        if hasattr(self, "_refresh_breathing_state_on_recover"):
            self._refresh_breathing_state_on_recover(curr_px, entry)
            return
        # Fallback should not run if mixin present
        if curr_px <= 0 or not entry:
            return
        if self.best_price == 0.0:
            self.best_price = entry
        if self.current_side == "LONG":
            self.best_price = max(self.best_price, curr_px)
        else:
            self.best_price = min(self.best_price, curr_px)
    def _radar_activation_progress(self, curr_px: float) -> float:
        if curr_px <= 0 or not self.watched_entry:
            return 0.0
        tp1 = float(self.tv_tps[0] or 0) if self.tv_tps else 0.0
        if tp1 > 0:
            return tp_path_progress(self.watched_entry, curr_px, tp1, self.current_side)
        return 0.0

    def _radar_trail_detail(self, curr_px: float, new_sl: float, **extra) -> dict:
        progress = self._radar_activation_progress(curr_px)
        tps = list(self.tv_tps or [])
        tp1 = float(tps[0] or 0) if tps else 0.0
        tp2 = float(tps[1] or 0) if len(tps) > 1 else 0.0
        tp3 = float(tps[2] or 0) if len(tps) > 2 else 0.0
        stage = detect_radar_stage(
            float(self.watched_entry or 0), curr_px, self.current_side, tp1, tp2, tp3,
            peak_px=float(self.best_price or 0) or None,
            tp1_filled=tp1_filled_from_consumed(getattr(self, "consumed_tp_levels", None)),
            armed=bool(
                getattr(self, "radar_activated", False)
                or getattr(self, "radar_latched", False)
            ),
            step_count=int(getattr(self, "radar_step_count", 0) or 0),
            regime=int(self.regime or 3),
        )
        vps_meta = getattr(self, "_vps_hard_sl_meta", None) or {}
        arm_meta = getattr(self, "_last_radar_arm_meta", None) or {}
        from app.core.radar_trail import radar_effective_activation, regime_radar_activation

        base_act = float(
            (self.regime_settings.get(self.regime) or {}).get("activation")
            or regime_radar_activation(int(self.regime or 3))
        )
        eff_act = float(
            arm_meta.get("activation_effective")
            or radar_effective_activation(
                int(self.regime or 3),
                float(self.watched_entry or 0),
                tp1,
                float(self.current_atr or 0),
            )
        )
        detail = {
            "regime": self.regime,
            "new_sl": new_sl,
            "best_price": self.best_price,
            "radar_progress": round(progress, 4),
            "radar_activation": base_act,
            "radar_activation_effective": round(eff_act, 4),
            "radar_arm_reason": arm_meta.get("arm_reason"),
            "tp1_span": arm_meta.get("tp1_span"),
            "favorable_move": arm_meta.get("favorable_move"),
            "min_abs_move": arm_meta.get("min_abs_move"),
            "radar_stage": stage,
            "consumed_tp_levels": list(getattr(self, "consumed_tp_levels", []) or []),
            "vps_hard_sl": float(getattr(self, "tv_sl", 0) or 0),
            "sl_distance": vps_meta.get("sl_distance"),
            "hard_sl_pct": vps_meta.get("hard_sl_pct"),
            "hard_sl_pct_display": vps_meta.get("hard_sl_pct_display"),
            "final_multiplier": vps_meta.get("final_multiplier") or vps_meta.get("hard_sl_pct"),
            "entry": float(self.watched_entry or 0),
            "tp1": tp1,
            "curr_px": curr_px,
            "exchange": self.exchange_id,
        }
        # Checklist 10.3: include floating PnL on each SL move notify
        entry = float(self.watched_entry or 0)
        qty = float(self.watched_qty or 0)
        if entry > 0 and qty > 0 and curr_px > 0:
            if self.current_side == "LONG":
                detail["floating_pnl"] = round((curr_px - entry) * qty, 4)
            elif self.current_side == "SHORT":
                detail["floating_pnl"] = round((entry - curr_px) * qty, 4)
        detail.update(extra)
        return detail

    def _sentinel_poll_sec(self, curr_px: float = 0.0) -> float:
        """REST sentinel cadence: ≥1s + jitter; order fills rely on user-data WS."""
        import random

        if self._breakeven_sl_active() or self._is_radar_engaged():
            base = SENTINEL_POLL_RADAR
        elif curr_px > 0 and tp1_filled_from_consumed(getattr(self, "consumed_tp_levels", None)):
            base = SENTINEL_POLL_RADAR
        elif curr_px > 0 and self.watched_entry and self.tv_tps:
            progress = self._radar_activation_progress(curr_px)
            act = 0.70
            if hasattr(self, "_regime_radar_activation"):
                act = float(self._regime_radar_activation() or 0.70)
            else:
                row = (self.regime_settings.get(self.regime) or {})
                act = float(row.get("activation") or 0.70)
            # Approaching arm threshold → poll at ~1s + jitter
            if progress + 1e-9 >= max(0.40, act * 0.55):
                base = SENTINEL_POLL_ARMING
            else:
                base = SENTINEL_POLL_NORMAL
        else:
            base = SENTINEL_POLL_NORMAL
        return float(base) + random.uniform(0.0, SENTINEL_POLL_JITTER_SEC)

    def _process_radar_trailing(self, real_amt: float, curr_px: float) -> bool:
        # TP limit timeout: only cancel if mark already reached the TP (stuck fill),
        # never cancel healthy resting TPs still away from market — that caused a
        # 5-min cancel→clear-consumed→nuclear-rehang loop and duplicate limits.
        try:
            import time as _t
            from app.core.tp_slice_guard import tp_would_instant_fill
            from app.core.vps_radar_stages import TP_LIMIT_TIMEOUT_SEC
            now = _t.time()
            placed = dict(getattr(self, "_tp_placed_at", None) or {})
            if placed:
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
                    # Healthy resting TP (price not reached) — refresh stamp, keep on book
                    if tp_px > 0 and float(curr_px or 0) > 0 and not tp_would_instant_fill(
                        self.current_side, tp_px, float(curr_px or 0),
                    ):
                        placed[lvl] = now
                        self._tp_placed_at = placed
                        if hasattr(self, "_save_state"):
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
                        if hasattr(self, "_save_state"):
                            self._save_state()
                        self._alert(
                            "warning", "TP_SKIP_REHANG", "TP挂单超时·移交呼吸止损",
                            f"TP{lvl} 超过{int(TP_LIMIT_TIMEOUT_SEC)}s且现价已过"
                            f"（撤单{cancelled}）·禁止重挂",
                            {
                                "level": int(lvl),
                                "cancelled": cancelled,
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
        from app.core.exchange_errors import ExchangeTransientError

        last_px = 0.0
        while self.monitoring:
            try:
                self._ensure_price_ws()
                if not self._lock.acquire(timeout=2.0):
                    continue
                try:
                    try:
                        pos = self.position_manager.get_position(self.symbol)
                    except ExchangeTransientError as e:
                        self._handle_position_query_failure(e)
                        # Do NOT treat as flat — skip this tick
                        continue
                    self._clear_position_query_degraded()
                    real_amt = float(pos.get("positionAmt", 0)) if pos else 0.0
                    actual_side = "LONG" if real_amt > 0 else "SHORT"
                    actual_qty = abs(real_amt)

                    if real_amt == 0:
                        if self.watched_qty > 0:
                            self._purge_defense_orders_on_flat(
                                "sentinel_zero_eager", notify=False,
                            )
                            if self._handle_detected_flat(
                                "sentinel_zero", skip_eager_purge=True,
                            ):
                                break
                        else:
                            break

                    if self.watched_qty > 0 and self._should_finalize_tp_victory(actual_qty):
                        self._sweep_dust_and_finalize(
                            "仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)"
                        )
                        break

                    if self._sentinel_force_align_if_opposite(actual_side):
                        break

                    entry_px = float(pos.get("entryPrice", 0) or self.watched_entry or 0)
                    curr_px = self.client.get_current_price(self.symbol, prefer_ws=True)
                    if curr_px <= 0:
                        curr_px = last_px
                    else:
                        last_px = curr_px

                    exposure = self._audit_live_exposure(
                        actual_qty,
                        actual_side,
                        position_amt=real_amt,
                        curr_px=curr_px,
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

                    qty_changed = qty_change_significant(
                        self.watched_qty,
                        actual_qty,
                        is_contracts=False,
                    )
                    booked_side = resolve_booked_side(
                        current_side=self.current_side,
                        last_tv_side=self.last_tv_side,
                    )
                    if qty_changed and booked_side and actual_side != booked_side:
                        exposure_flip = self._audit_live_exposure(
                            actual_qty, actual_side, position_amt=real_amt, curr_px=curr_px,
                        )
                        self._remediate_exposure_anomaly(
                            exposure_flip, entry_px, trigger="sentinel_qty_flip", curr_px=curr_px,
                        )
                        break
                    if qty_changed:
                        old_qty = self.watched_qty
                        orch = self._orchestrate_qty_change(
                            old_qty,
                            actual_qty,
                            float(pos.get("entryPrice", 0) or self.watched_entry or 0),
                            curr_px or float(pos.get("entryPrice", 0) or 0),
                        )
                        self.watched_qty = actual_qty
                        self.watched_entry = float(pos["entryPrice"])
                        change_type = orch.get("change_type", "manual_reduce")
                        result = orch.get("defense") or {}
                        action_msg = orch.get("action_msg", change_type)

                        detail = {
                            "old_qty": old_qty,
                            "new_qty": actual_qty,
                            "entry": self.watched_entry,
                            "initial_qty": float(self.initial_qty or 0),
                            "change_type": change_type,
                            "consumed_tp_levels": list(self.consumed_tp_levels),
                            "adverse_consumed_tiers": list(self.adverse_consumed_tiers),
                            "action_msg": action_msg,
                            "defense": result,
                            "orchestration": orch,
                        }
                        self._log(
                            "ADJUST",
                            f"🔄 智能感知仓位变化 [{change_type}]: {old_qty} ➔ {actual_qty} | "
                            f"TP {result.get('matched', 0)}/{result.get('expected', 0)}",
                            detail,
                        )
                        if change_type.startswith("tp"):
                            alert_type = "TP_FILL"
                            title = f"部分止盈吃单 · {change_type.upper()}"
                            severity = "info"
                        else:
                            alert_type = "MANUAL_ADJUST"
                            title = f"阵地异动 · {action_msg}"
                            severity = "warning"
                        self._alert(
                            severity, alert_type,
                            title,
                            f"数量 {old_qty} → {actual_qty} @ {self.watched_entry} | "
                            f"初始{float(self.initial_qty or 0)} | "
                            f"{self._format_audit_summary((result.get('audit') or {}))}",
                            detail,
                        )
                        if result.get("expected", 0) > 0 and result.get("matched", 0) < result.get("expected", 0):
                            self._alert(
                                "warning", "DEFENSE",
                                "异动后止盈未对齐",
                                self._format_audit_summary(result.get("audit") or {}),
                                result,
                            )
                        self._save_state()

                    self._scan_ticks += 1
                    now_ts = time.time()
                    last_audit = float(getattr(self, "_last_tp_audit_ts", 0) or 0)
                    if curr_px > 0:
                        self.best_price = (
                            max(self.best_price, curr_px)
                            if self.current_side == "LONG"
                            else min(self.best_price, curr_px)
                        )
                        # 先按「价到+限价消失」记账，再决定是否补挂（避免误补 TP1）
                        before_c = set(int(x) for x in (self.consumed_tp_levels or []))
                        self._sync_consumed_tp_levels(actual_qty, curr_px)
                        after_c = set(int(x) for x in (self.consumed_tp_levels or []))
                        gained_c = sorted(after_c - before_c)
                        if gained_c:
                            self._notify_tp_fill_detected(
                                gained_c[0], self.watched_qty, actual_qty, curr_px,
                            )

                    # Order-book REST audit ≤ every 2s (fills prefer user-data WS)
                    if (
                        not qty_changed
                        and (now_ts - last_audit) >= SENTINEL_ORDER_AUDIT_SEC
                    ):
                        self._last_tp_audit_ts = now_ts
                        audit = self._audit_tp_levels(actual_qty, curr_px=curr_px or None)
                        if audit["issues"]:
                            logger.info(
                                f"[User {self.user_id}] 🔍 定期扫描发现异常: {audit['issues']}，触发智能补挂"
                            )
                            sl_to_pass = self._radar_sl_to_pass()
                            self._smart_realign_defenses(
                                actual_qty,
                                self.watched_entry,
                                dynamic_sl=None,
                                reason="定期防线扫描·仅TP限价·不碰雷达硬止损",
                            )
                            if sl_to_pass and hasattr(self, "_ensure_radar_sl"):
                                self._ensure_radar_sl(sl_to_pass, actual_qty)
                            elif sl_to_pass and hasattr(self, "_sync_binance_merged_stop"):
                                self._sync_binance_merged_stop(
                                    actual_qty, radar_sl=sl_to_pass, force_replace=True,
                                )

                    if curr_px > 0:
                        self._orchestrate_defense_monitoring(actual_qty, curr_px)

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
        tv_reason: str | None = None,
        tv_close_ctx: dict | None = None,
        attribution: dict | None = None,
        close_trigger: str | None = None,
    ):
        pos_before = self.position_manager.get_position(self.symbol)
        had_position = bool(
            pos_before and float(pos_before.get("positionAmt", 0) or 0) != 0
        )
        self._purge_defense_orders_on_flat(
            close_trigger or "code_close_all", notify=False,
        )
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
                    "reason": tv_reason or reason,
                    "tv_reason": tv_reason or reason,
                    "action": "cancel_orders_reset",
                    "exchange": self.exchange_id,
                }
                if tv_close_ctx:
                    empty_detail.update({k: v for k, v in tv_close_ctx.items() if v is not None})
                if tv_pnl_pct is not None:
                    empty_detail["tv_pnl_pct"] = round(float(tv_pnl_pct), 2)
                self._log(
                    "CLOSE_PROTECT_EMPTY",
                    f"🛡️ 空仓复位：撤单复位（{reason.split('：', 1)[-1] if '：' in reason else reason}）",
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
                display_reason = tv_reason or reason
                if attribution is None:
                    trigger = close_trigger or ("tv_signal" if close_action else "code_close_all")
                    attribution = self._diagnose_flat_close(
                        trigger,
                        had_position,
                        platform_market=had_position,
                    )
                    if not close_action:
                        display_reason = format_close_reason(attribution)
                sev = "critical" if "背离" in display_reason else "info"
                self._record_trade_close(
                    display_reason,
                    exit_price,
                    attribution=attribution,
                    close_action=close_action,
                    tv_side=tv_side,
                    tv_pnl_pct=tv_pnl_pct,
                    tv_reason=tv_reason or display_reason,
                    tv_close_ctx=tv_close_ctx,
                    alert_sev=sev,
                )

        if closed_successfully and had_position:
            self._trigger_settlement_on_flat()
        elif had_position and not closed_successfully:
            residual_amt = 0.0
            pos = self.position_manager.get_position(self.symbol)
            if pos:
                residual_amt = abs(float(pos.get("positionAmt", 0) or 0))
            fail_detail = {
                "reason": reason,
                "close_action": close_action,
                "residual_qty": residual_amt,
                "exit_price": exit_price,
            }
            self._log(
                "CLOSE_FAIL",
                f"❌ 清仓未完全归零，残仓 {residual_amt} ETH",
                fail_detail,
            )
            self._alert(
                "critical",
                "CLOSE_FAIL",
                "清仓失败 · 请人工核查",
                f"平台强平后仍剩 {residual_amt} {getattr(self, 'qty_unit', 'ETH')} | {reason}",
                fail_detail,
            )

        self.monitoring = False
        self._unbind_price_ws_listener()
        self._disarm_adverse_staged_stops(reason="flat_reset", notify=False)
        if hasattr(self, "_clear_position_local_state"):
            self._clear_position_local_state()
        else:
            self._reset_adverse_radar(keep_tv_sl=False)
            self.watched_qty = 0.0
            self.watched_entry = 0.0
            self.initial_qty = 0.0
            self.base_qty = 0.0
            self.add_count = 0
            self.consumed_tp_levels = []
            self._tp_fill_dingtalk_levels = set()
            self.current_side = None
            self.best_price = 0.0
            self.current_trade_id = None
            self.trade_opened_at = None
        self._save_state()
        self._purge_defense_orders_on_flat("flat_reset", notify=True)
        if closed_successfully:
            self._reconcile_live_vs_book(
                expect_flat=True,
                context=str(close_action or close_trigger or "close"),
                notify_ok=False,
            )

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
                trade = recovery_section(recovery_context, "trade")
                if open_trade_id is None and trade.get("id"):
                    open_trade_id = trade["id"]
                    audit["open_trade_id"] = open_trade_id

            saved_state_tv_side = self.last_tv_side
            if recovery_context is not None:
                recovery_context = dict(recovery_context)
                recovery_context["state_last_tv_side"] = saved_state_tv_side
            reconcile = self._reconcile_radar_context(recovery_context)
            reconcile["state_last_tv_side"] = saved_state_tv_side
            audit["state_last_tv_side"] = saved_state_tv_side
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
                if not self._idle_book_is_flat():
                    self._recover_missed_flat_on_startup(was_monitoring=saved_monitoring)
                else:
                    self._idle_cancel_orphan_orders_when_flat()
                self._log("STARTUP", "VPS 自启审计：空仓待机", reconcile)
                return audit

            real_amt = float(pos["positionAmt"])
            self.current_side = "LONG" if real_amt > 0 else "SHORT"

            self.watched_qty = abs(real_amt)
            open_log_qty = float(reconcile.get("open_log_qty") or 0)
            trade_ctx = recovery_section(recovery_context, "trade")
            trade_qty = float(trade_ctx.get("quantity") or 0)
            saved_initial = float(self.initial_qty or 0)
            restored = max(saved_initial, open_log_qty, trade_qty)
            if restored > self.watched_qty:
                self.initial_qty = restored
            elif saved_initial <= 0:
                self.initial_qty = self.watched_qty
            if float(getattr(self, "base_qty", 0) or 0) <= 0:
                self.base_qty = float(open_log_qty or trade_qty or self.initial_qty or self.watched_qty)
            # 妈妈版：永不推断加仓次数
            self.add_count = 0
            self.watched_entry = float(pos["entryPrice"])
            self.current_trade_id = open_trade_id
            if hasattr(self, "_recompute_vps_hard_sl") and self.current_side in ("LONG", "SHORT"):
                from app.core.startup_reconcile import recompute_vps_hard_sl_on_recovery
                sl_meta = recompute_vps_hard_sl_on_recovery(
                    self, entry_px=self.watched_entry, side=self.current_side,
                )
                audit["vps_hard_sl_meta"] = sl_meta
            if not open_trade_id and not trade_ctx:
                audit["adopted_manual"] = True
                audit["adopt_source"] = "unregistered_live"
                prepare_manual_adopt(self)
                adopt_msg = "未登记来源仓位·系统接管（来源待核实）"
                self._log(
                    "STARTUP",
                    f"{adopt_msg}: {self.current_side} {self.watched_qty} @ {self.watched_entry} "
                    f"| SL={getattr(self, 'initial_stop', 0) or getattr(self, 'tv_sl', 0)} "
                    f"ATR={getattr(self, 'initial_atr', 0) or getattr(self, 'current_atr', 0)}",
                )
                self._alert(
                    "warning",
                    "STARTUP",
                    "未登记来源仓位 · 系统接管",
                    adopt_msg,
                    {
                        "adopt_source": "unregistered_live",
                        "side": self.current_side,
                        "qty": self.watched_qty,
                        "entry": self.watched_entry,
                        "initial_stop": float(getattr(self, "initial_stop", 0) or 0),
                        "initial_atr": float(getattr(self, "initial_atr", 0) or 0),
                        "tv_tps": list(getattr(self, "tv_tps", []) or []),
                        "source_verified": False,
                    },
                )

            side_sync = self._try_force_align_opposite_to_tv(
                reconcile,
                adopted_manual=bool(
                    audit.get("adopted_manual")
                    or live_matches_entry_direction(reconcile, self.current_side)
                ),
                trigger="startup",
            )
            audit["tv_side_sync"] = side_sync
            if side_sync.get("paused"):
                audit["trading_paused"] = True
                audit["has_position"] = True
                audit["direction_aligned"] = False
                audit["side"] = self.current_side
                audit["qty"] = self.watched_qty
                audit["entry"] = self.watched_entry
                audit["monitoring"] = False
                audit["startup_summary"] = (
                    f"方向不一致已暂停 · 实盘{self.current_side} vs TV{side_sync.get('tv_side')}"
                )
                self.monitoring = False
                self._save_state()
                self._log("STARTUP", audit["startup_summary"], audit)
                return audit
            if side_sync.get("force_aligned"):
                audit["force_aligned"] = True
                audit["has_position"] = False
                audit["direction_aligned"] = True
                audit["side"] = None
                audit["qty"] = 0.0
                audit["monitoring"] = False
                audit["startup_summary"] = f"逆势持仓已强平 · 对齐 TV {side_sync.get('tv_side')}"
                self._log(
                    "STARTUP",
                    audit["startup_summary"],
                    audit,
                )
                self._alert(
                    "critical",
                    "FORCE_ALIGN",
                    "VPS 重启 · 方向不一致强制平仓对齐 TV",
                    audit["startup_summary"],
                    audit,
                )
                self._save_state()
                return audit
            if side_sync.get("conflict"):
                audit.setdefault("warnings", []).append("tv_opposite_force_flat")

            # Checklist §六: old radar schema → alert + pause (no auto-migrate)
            if bool(getattr(self, "_state_schema_legacy", False)) and (
                float(getattr(self, "initial_atr", 0) or 0) <= 0
                or float(getattr(self, "initial_stop", 0) or 0) <= 0
            ):
                msg = "重启检测到旧雷达schema(activated/stepCount)且无initialAtr · 暂停交易"
                if hasattr(self, "_pause_trading"):
                    self._pause_trading(msg, {
                        "schema_legacy": True,
                        "side": self.current_side,
                        "qty": self.watched_qty,
                    })
                audit["trading_paused"] = True
                audit["startup_summary"] = msg
                self.monitoring = False
                self._save_state()
                self._log("STARTUP", msg, audit)
                return audit

            # Checklist §七: position exists but no persisted TP / breathing stop → alert + pause
            has_persist_tp = any(float(x or 0) > 0 for x in (self.tv_tps or [])[:2])
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
                        "side": self.current_side,
                        "qty": self.watched_qty,
                        "entry": self.watched_entry,
                        "initial_atr": getattr(self, "initial_atr", 0),
                        "initial_stop": getattr(self, "initial_stop", 0),
                        "current_sl": getattr(self, "current_sl", 0),
                    })
                audit["trading_paused"] = True
                audit["has_position"] = True
                audit["side"] = self.current_side
                audit["qty"] = self.watched_qty
                audit["entry"] = self.watched_entry
                audit["monitoring"] = False
                audit["startup_summary"] = msg
                self.monitoring = False
                self._save_state()
                self._log("STARTUP", msg, audit)
                return audit

            if self.best_price <= 0:
                self.best_price = self.watched_entry
            # Breathing stop: restore current_sl from initial_stop if needed
            if float(self.current_sl or 0) <= 0:
                self.current_sl = float(
                    getattr(self, "initial_stop", 0) or getattr(self, "tv_sl", 0) or 0
                )

            curr_px = self.client.get_current_price(self.symbol)
            self._sync_consumed_tp_levels(self.watched_qty, curr_px or self.watched_entry)
            self._refresh_radar_state_on_recover(curr_px, self.watched_entry)

            cap_result = self._enforce_regime_cap_alignment(
                self.watched_qty,
                self.watched_entry,
                curr_px or self.watched_entry,
                reason="重启恢复",
            )
            if cap_result.get("new_qty"):
                self.watched_qty = float(cap_result["new_qty"])

            unified = self._unified_startup_defense_reconcile(
                self.watched_qty,
                self.watched_entry,
                curr_px or self.watched_entry,
                cap_result=cap_result,
                reason="VPS/部署重启",
            )
            defense = unified.get("tp_defense") or {}
            adverse_startup = unified.get("shield") or {}

            audit["direction_aligned"] = (
                self.current_side == self.last_tv_side if self.last_tv_side else True
            )
            if side_sync.get("realigned"):
                audit["direction_aligned"] = True
            if reconcile.get("warnings"):
                audit["radar_warnings"] = reconcile["warnings"]

            self.monitoring = True
            self._ensure_price_ws()

            audit.update({
                "has_position": True,
                "side": self.current_side,
                "qty": self.watched_qty,
                "entry": self.watched_entry,
                "base_qty": float(getattr(self, "base_qty", 0) or 0),
                "add_count": int(getattr(self, "add_count", 0) or 0),
                "last_tv_side": self.last_tv_side,
                "latest_tv_action": reconcile.get("latest_tv_action"),
                "latest_tv_at": reconcile.get("latest_tv_at"),
                "open_log_side": reconcile.get("open_log_side"),
                "open_log_qty": reconcile.get("open_log_qty"),
                "open_log_entry": reconcile.get("open_log_entry"),
                "tv_tps": list(self.tv_tps),
                "current_sl": self.current_sl,
                "best_price": self.best_price,
                "breakeven_active": unified.get("breakeven_active", False),
                "radar_sl": unified.get("radar_sl"),
                "consumed_tp_levels": list(self.consumed_tp_levels),
                "monitoring": True,
                "pnl_track": unified.get("pnl_track"),
                "floating_profit": unified.get("floating_profit"),
                "adverse_pct": unified.get("adverse_pct"),
                "radar_progress": unified.get("radar_progress"),
                "startup_summary": unified.get("startup_summary"),
                "defenses_rebuilt": unified.get("defenses_rebuilt", False),
                "defenses_skipped": unified.get("defenses_skipped", False),
                "defenses_aligned": unified.get("defenses_aligned", False),
                "defense_summary": unified.get("defense_summary"),
                "tp_matched": unified.get("tp_matched"),
                "tp_expected": unified.get("tp_expected"),
                "adverse_startup": adverse_startup,
                "shield_stop_price": unified.get("shield_stop_price"),
                "radar_handoff": unified.get("radar_handoff"),
                "radar_permitted": unified.get("radar_permitted"),
                "tv_sl": float(getattr(self, "tv_sl", 0) or 0),
            })
            self._save_state()

            self._log(
                "STARTUP",
                f"雷达接管 {self.current_side} {self.watched_qty} @ {self.watched_entry} | "
                f"TV={self.last_tv_side} TP={self.tv_tps}",
                audit,
            )
            summary = audit.get("startup_summary") or format_startup_defense_summary(audit)
            self._alert(
                "info", "STARTUP",
                "VPS 雷达智能接管完成",
                f"{self.current_side} {self.watched_qty} @ {self.watched_entry} | {summary}",
                audit,
            )
            threading.Thread(target=self._sentinel_loop, daemon=True).start()
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
