"""Trade ledger + state machine — single source of truth for the open pipeline.

Roles (Gemini multi-user; same phase names as 币安单系编制):
  Signal → Admission → PositionAuditor → Execution → Radar → ChiefAuditor → Communications

Phases advance only via ``TradeLedger.advance``; officers must not skip or race.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TradePhase(str, Enum):
    IDLE = "IDLE"
    SIGNAL_RECEIVED = "SIGNAL_RECEIVED"
    PENDING_CLEAR = "PENDING_CLEAR"
    CLEARED = "CLEARED"
    ENTRY_SUBMITTED = "ENTRY_SUBMITTED"
    ENTRY_CONFIRMED = "ENTRY_CONFIRMED"
    ORDERS_PLACED = "ORDERS_PLACED"
    VERIFIED = "VERIFIED"
    REPORTED = "REPORTED"
    FAILED = "FAILED"
    FLAT = "FLAT"


_FORWARD: dict[TradePhase, frozenset[TradePhase]] = {
    TradePhase.IDLE: frozenset({TradePhase.SIGNAL_RECEIVED}),
    TradePhase.SIGNAL_RECEIVED: frozenset({TradePhase.PENDING_CLEAR, TradePhase.FAILED}),
    TradePhase.PENDING_CLEAR: frozenset({TradePhase.CLEARED, TradePhase.FAILED}),
    TradePhase.CLEARED: frozenset({TradePhase.ENTRY_SUBMITTED, TradePhase.FAILED}),
    TradePhase.ENTRY_SUBMITTED: frozenset({TradePhase.ENTRY_CONFIRMED, TradePhase.FAILED}),
    TradePhase.ENTRY_CONFIRMED: frozenset({TradePhase.ORDERS_PLACED, TradePhase.FAILED}),
    TradePhase.ORDERS_PLACED: frozenset({TradePhase.VERIFIED, TradePhase.FAILED}),
    TradePhase.VERIFIED: frozenset({TradePhase.REPORTED, TradePhase.FAILED, TradePhase.FLAT}),
    TradePhase.REPORTED: frozenset({TradePhase.FLAT, TradePhase.FAILED, TradePhase.ORDERS_PLACED}),
    TradePhase.FAILED: frozenset({TradePhase.IDLE, TradePhase.SIGNAL_RECEIVED, TradePhase.FLAT}),
    TradePhase.FLAT: frozenset({TradePhase.IDLE, TradePhase.SIGNAL_RECEIVED}),
}

PHASE_STALL_SEC: dict[TradePhase, float] = {
    TradePhase.SIGNAL_RECEIVED: 60.0,
    TradePhase.PENDING_CLEAR: 45.0,
    TradePhase.CLEARED: 30.0,
    TradePhase.ENTRY_SUBMITTED: 30.0,
    TradePhase.ENTRY_CONFIRMED: 60.0,
    TradePhase.ORDERS_PLACED: 45.0,
    TradePhase.VERIFIED: 30.0,
}


@dataclass
class AuditorFinding:
    ok: bool
    item: str
    detail: str = ""


@dataclass
class TradeLedgerSnapshot:
    schema_version: int = 1
    phase: str = TradePhase.IDLE.value
    phase_entered_at: float = 0.0
    user_id: int | None = None
    exchange: str = ""
    symbol: str = ""
    side: str = ""
    qty: float = 0.0
    initial_qty: float = 0.0
    entry_price: float = 0.0
    opened_at: float = 0.0
    tier: str = ""
    signal_action: str = ""
    margin_pct_frac: float = 0.20
    leverage: int = 5
    hard_sl_price: float = 0.0
    hard_sl_order_id: str | None = None
    hard_sl_hung: bool = False
    tp1_price: float = 0.0
    tp1_qty: float = 0.0
    tp1_order_id: str | None = None
    tp1_filled: bool = False
    tp2_price: float = 0.0
    tp2_qty: float = 0.0
    tp2_order_id: str | None = None
    tp2_filled: bool = False
    radar_activated: bool = False
    radar_sl_price: float = 0.0
    radar_order_id: str | None = None
    last_audit_ok: bool | None = None
    last_audit_failures: list[str] = field(default_factory=list)
    last_audit_at: float = 0.0
    api_call_ts: list[float] = field(default_factory=list)
    book_suspect: bool = False
    fail_reason: str = ""
    updated_at: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)


class TradeLedger:
    MAX_EVENTS = 80
    MAX_API_TS = 64

    def __init__(
        self,
        *,
        user_id: int,
        exchange: str,
        symbol: str,
        state_dir: str | Path | None = None,
    ):
        self._lock = threading.RLock()
        self.snap = TradeLedgerSnapshot(
            user_id=int(user_id),
            exchange=str(exchange or "binance").lower(),
            symbol=str(symbol or "").upper(),
            phase_entered_at=time.time(),
            updated_at=time.time(),
        )
        base = Path(state_dir) if state_dir else self._default_dir()
        safe_sym = self.snap.symbol.replace("/", "_").lower()
        self._path = base / f"ledger_{self.snap.exchange}_{self.snap.user_id}_{safe_sym}.json"
        self._load()

    @staticmethod
    def _default_dir() -> Path:
        try:
            from app.config import get_settings

            root = Path(getattr(get_settings(), "DATA_DIR", None) or "data")
        except Exception:
            root = Path("data")
        d = root / "supervisor" / "ledgers"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for k, v in raw.items():
                if hasattr(self.snap, k):
                    setattr(self.snap, k, v)
        except Exception as e:
            logger.warning("ledger load failed %s: %s", self._path, e)

    def persist(self) -> None:
        with self._lock:
            self.snap.updated_at = time.time()
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(asdict(self.snap), ensure_ascii=False, indent=0),
                    encoding="utf-8",
                )
                os.replace(tmp, self._path)
            except Exception as e:
                logger.warning("ledger persist failed: %s", e)

    def phase(self) -> TradePhase:
        try:
            return TradePhase(self.snap.phase)
        except ValueError:
            return TradePhase.IDLE

    def note_event(self, kind: str, detail: dict | None = None) -> None:
        with self._lock:
            self.snap.events.append(
                {"ts": time.time(), "kind": kind, "detail": dict(detail or {})}
            )
            if len(self.snap.events) > self.MAX_EVENTS:
                self.snap.events = self.snap.events[-self.MAX_EVENTS :]
            self.snap.updated_at = time.time()

    def note_api_call(self) -> None:
        with self._lock:
            now = time.time()
            self.snap.api_call_ts.append(now)
            cutoff = now - 60.0
            self.snap.api_call_ts = [t for t in self.snap.api_call_ts if t >= cutoff][
                -self.MAX_API_TS :
            ]

    def api_calls_last_min(self) -> int:
        with self._lock:
            cutoff = time.time() - 60.0
            return sum(1 for t in self.snap.api_call_ts if t >= cutoff)

    def advance(self, to: TradePhase, *, reason: str = "", force: bool = False) -> bool:
        with self._lock:
            cur = self.phase()
            if cur == to:
                return True
            allowed = _FORWARD.get(cur, frozenset())
            if (
                not force
                and to not in allowed
                and to not in (TradePhase.FAILED, TradePhase.FLAT)
            ):
                logger.error(
                    "ledger refuse advance %s → %s (%s)",
                    cur.value,
                    to.value,
                    reason,
                )
                self.note_event(
                    "ADVANCE_REFUSED",
                    {"from": cur.value, "to": to.value, "reason": reason},
                )
                return False
            self.snap.phase = to.value
            self.snap.phase_entered_at = time.time()
            if to == TradePhase.FAILED:
                self.snap.fail_reason = str(reason or "")[:400]
            if to in (TradePhase.FLAT, TradePhase.IDLE):
                self.snap.book_suspect = False
            self.note_event("PHASE", {"to": to.value, "reason": reason})
            self.persist()
            return True

    def stall_seconds(self) -> float:
        return max(0.0, time.time() - float(self.snap.phase_entered_at or 0))

    def is_stalled(self) -> bool:
        budget = PHASE_STALL_SEC.get(self.phase())
        if not budget:
            return False
        return self.stall_seconds() > budget

    def sync_from_supervisor(self, host: Any) -> None:
        with self._lock:
            self.snap.side = str(getattr(host, "current_side", None) or self.snap.side or "")
            self.snap.qty = float(getattr(host, "watched_qty", 0) or 0)
            iq = float(getattr(host, "initial_qty", 0) or 0)
            if iq > 0 and (
                float(self.snap.initial_qty or 0) <= 0
                or not bool(getattr(host, "monitoring", False))
                or iq + 1e-12 >= float(self.snap.initial_qty or 0)
            ):
                self.snap.initial_qty = max(float(self.snap.initial_qty or 0), iq)
            self.snap.entry_price = float(getattr(host, "watched_entry", 0) or 0)
            self.snap.hard_sl_price = float(
                getattr(host, "tv_hard_sl_price", 0)
                or getattr(host, "frozen_hard_stop_px", 0)
                or 0
            )
            ids = dict(getattr(host, "_defense_order_ids", None) or {})
            if ids.get("hard"):
                self.snap.hard_sl_order_id = str(ids.get("hard"))
                self.snap.hard_sl_hung = True
            if ids.get("radar") or ids.get("sl"):
                self.snap.radar_order_id = str(ids.get("radar") or ids.get("sl"))
            self.snap.radar_activated = bool(
                getattr(host, "radar_latched", False)
                or getattr(host, "radar_activated", False)
            )
            self.snap.radar_sl_price = float(getattr(host, "current_sl", 0) or 0)
            tps = list(getattr(host, "tv_tps", None) or [])
            if len(tps) >= 1:
                self.snap.tp1_price = float(tps[0] or 0)
            if len(tps) >= 2:
                self.snap.tp2_price = float(tps[1] or 0)
            consumed = {int(x) for x in (getattr(host, "consumed_tp_levels", None) or [])}
            self.snap.tp1_filled = 1 in consumed
            self.snap.tp2_filled = 2 in consumed
            self.snap.margin_pct_frac = float(
                getattr(host, "entry_margin_pct", None)
                or self.snap.margin_pct_frac
                or 0.20
            )
            try:
                self.snap.leverage = int(
                    getattr(host, "entry_leverage", None)
                    or getattr(host, "leverage", None)
                    or self.snap.leverage
                    or 5
                )
            except (TypeError, ValueError):
                pass
            self.snap.updated_at = time.time()

    def set_tp_slices(self, slices: list[tuple[int, float, float]]) -> None:
        with self._lock:
            for lv, q, px in slices:
                if int(lv) == 1:
                    self.snap.tp1_qty = float(q)
                    self.snap.tp1_price = float(px)
                elif int(lv) == 2:
                    self.snap.tp2_qty = float(q)
                    self.snap.tp2_price = float(px)

    def mark_audit(self, findings: list[AuditorFinding]) -> bool:
        ok = all(f.ok for f in findings)
        with self._lock:
            self.snap.last_audit_ok = ok
            self.snap.last_audit_failures = [
                f"{f.item}: {f.detail}" for f in findings if not f.ok
            ]
            self.snap.last_audit_at = time.time()
            self.note_event(
                "AUDIT",
                {"ok": ok, "failures": list(self.snap.last_audit_failures)},
            )
            self.persist()
        return ok

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self.snap)


def ledger_for(host: Any) -> TradeLedger:
    existing = getattr(host, "_trade_ledger", None)
    if isinstance(existing, TradeLedger):
        return existing
    uid = int(getattr(host, "user_id", 0) or 0)
    ex = str(getattr(host, "exchange_id", None) or "binance")
    sym = str(
        getattr(host, "canonical_symbol", None) or getattr(host, "symbol", None) or ""
    )
    led = TradeLedger(user_id=uid, exchange=ex, symbol=sym)
    host._trade_ledger = led
    return led
