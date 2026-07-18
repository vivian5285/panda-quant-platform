"""TradingView bar_index + seq reorder gate.

Sort key: (bar_index ASC, seq ASC, close-before-open, enqueued_at ASC).

TV same-bar reality (VPS 必读):
  - Only CLOSE_*  → flatten
  - CLOSE_* then OPEN (refresh): close seq < open seq → sort naturally close→open
  - Never simultaneous "open then close" as two live alerts (open is overwritten)
  - Safety: equal seq still prefers CLOSE before OPEN; rare seq recycle still handled

If a higher seq arrives before a missing lower seq, hold WEBHOOK_SEQ_WAIT_SEC,
then alert and force-release in order.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.config import get_settings

logger = logging.getLogger(__name__)

DispatchFn = Callable[[dict, str], None]


@dataclass
class _Pending:
    payload: dict
    fingerprint: str
    symbol: str
    bar_index: int
    seq: int
    action: str
    enqueued_at: float = field(default_factory=time.time)


@dataclass
class _BarState:
    last_seq: int = 0
    last_action: str = ""
    released_fps: set[str] = field(default_factory=set)
    cycle: int = 0


class WebhookSeqGate:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: list[_Pending] = []
        self._timer: threading.Timer | None = None
        self._dispatch: DispatchFn | None = None
        # per (symbol, bar_index)
        self._bars: dict[tuple[str, int], _BarState] = {}

    def set_dispatch(self, fn: DispatchFn) -> None:
        self._dispatch = fn

    def pending_depth(self) -> int:
        with self._lock:
            return len(self._pending)

    def submit(self, payload: dict, fingerprint: str, *, dispatch: DispatchFn | None = None) -> str:
        """
        Enqueue or pass-through. Returns disposition: immediate | buffered | flushed.
        """
        fn = dispatch or self._dispatch
        if dispatch is not None:
            self._dispatch = dispatch
        if fn is None:
            raise RuntimeError("WebhookSeqGate dispatch callback not set")

        bi = payload.get("bar_index")
        seq = payload.get("seq")
        if bi is None or seq is None:
            fn(payload, fingerprint)
            return "immediate"

        try:
            bi_i = int(bi)
            seq_i = int(seq)
        except (TypeError, ValueError):
            fn(payload, fingerprint)
            return "immediate"

        if seq_i < 1:
            fn(payload, fingerprint)
            return "immediate"

        from app.core.symbol_registry import extract_payload_symbol

        symbol = extract_payload_symbol(payload, require=False) or "UNKNOWN"
        action = str(payload.get("action", "")).upper()
        item = _Pending(
            payload=payload,
            fingerprint=fingerprint,
            symbol=symbol,
            bar_index=bi_i,
            seq=seq_i,
            action=action,
            enqueued_at=time.time(),
        )
        with self._lock:
            # Drop exact fingerprint duplicates still buffered
            self._pending = [
                p for p in self._pending
                if p.fingerprint != fingerprint
            ]
            state = self._bars.setdefault((symbol, bi_i), _BarState())
            if fingerprint in state.released_fps:
                logger.info(
                    "[WebhookSeq] drop duplicate-fp symbol=%s bar=%s seq=%s action=%s",
                    symbol, bi_i, seq_i, action,
                )
                return "duplicate"

            self._pending.append(item)
            logger.info(
                "[WebhookSeq] buffered symbol=%s bar_index=%s seq=%s action=%s depth=%s cycle=%s",
                symbol,
                bi_i,
                seq_i,
                action,
                len(self._pending),
                state.cycle,
            )
            released = self._flush_locked(fn, force=False)
            self._arm_timer_locked()
        return "flushed" if released else "buffered"

    def flush_now(self) -> int:
        """Force flush all pending (tests / shutdown)."""
        fn = self._dispatch
        if fn is None:
            return 0
        with self._lock:
            return self._flush_locked(fn, force=True)

    def _wait_sec(self) -> float:
        return max(0.5, float(getattr(get_settings(), "WEBHOOK_SEQ_WAIT_SEC", 3.0) or 3.0))

    def _arm_timer_locked(self) -> None:
        if not self._pending:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            return
        if self._timer:
            self._timer.cancel()
        wait = self._wait_sec()
        oldest = min(p.enqueued_at for p in self._pending)
        delay = max(0.05, wait - (time.time() - oldest))
        t = threading.Timer(delay, self._on_timer)
        t.daemon = True
        self._timer = t
        t.start()

    def _on_timer(self) -> None:
        fn = self._dispatch
        if fn is None:
            return
        with self._lock:
            self._timer = None
            self._flush_locked(fn, force=False)
            if self._pending:
                self._flush_locked(fn, force=True)
            self._arm_timer_locked()

    def _bar_state(self, symbol: str, bar_index: int) -> _BarState:
        return self._bars.setdefault((symbol, bar_index), _BarState())

    def _mark_released(self, symbol: str, bar_index: int, item: _Pending) -> None:
        state = self._bar_state(symbol, bar_index)
        # Cycle restart: OPEN seq:1 after a higher seq (1-2-1). Not same-seq CLOSE→OPEN.
        if state.last_seq >= 2 and item.seq == 1 and item.seq < state.last_seq:
            state.cycle += 1
            logger.info(
                "[WebhookSeq] cycle-restart symbol=%s bar=%s seq=%s action=%s cycle=%s",
                symbol, bar_index, item.seq, item.action, state.cycle,
            )
        state.last_seq = item.seq
        state.last_action = item.action
        state.released_fps.add(item.fingerprint)
        # prune old bars for this symbol (keep last few)
        bars = sorted(b for (s, b) in self._bars if s == symbol)
        for old in bars[:-8]:
            self._bars.pop((symbol, old), None)

    @staticmethod
    def _action_rank(action: str) -> int:
        """CLOSE before OPEN when seq ties (TV refresh never opens before close)."""
        a = str(action or "").upper()
        if a.startswith("CLOSE"):
            return 0
        if a in ("LONG", "SHORT", "BUY", "SELL") or a.startswith("OPEN"):
            return 1
        return 2

    def _sort_key(self, p: _Pending) -> tuple:
        return (p.seq, self._action_rank(p.action), p.enqueued_at)

    def _is_ready(self, item: _Pending, last_seq: int, *, last_action: str = "") -> bool:
        """Contiguous next seq; CLOSE→OPEN same seq; rare seq recycle."""
        if last_seq <= 0:
            return item.seq == 1
        if item.seq == last_seq + 1:
            return True
        # Same seq: after CLOSE, allow OPEN (tie-break companion)
        if (
            item.seq == last_seq
            and str(last_action).upper().startswith("CLOSE")
            and self._action_rank(item.action) == 1
        ):
            return True
        # Legacy recycle safety (OPEN seq:1 after CLOSE seq:2)
        if item.seq == 1 and last_seq >= 2:
            return True
        return False

    def _flush_locked(self, fn: DispatchFn, *, force: bool) -> int:
        if not self._pending:
            return 0
        wait = self._wait_sec()
        now = time.time()
        released_n = 0

        symbols = sorted({p.symbol for p in self._pending})
        for symbol in symbols:
            while True:
                group_bars = sorted({p.bar_index for p in self._pending if p.symbol == symbol})
                if not group_bars:
                    break
                bar = group_bars[0]
                bucket = [p for p in self._pending if p.symbol == symbol and p.bar_index == bar]
                # seq ASC, CLOSE before OPEN, then arrival
                bucket.sort(key=self._sort_key)
                state = self._bar_state(symbol, bar)
                age = now - min(p.enqueued_at for p in bucket)
                timed_out = force or age >= wait

                ready: list[_Pending] = []
                last = state.last_seq
                last_action = state.last_action
                for p in bucket:
                    if p.fingerprint in state.released_fps:
                        self._pending.remove(p)
                        continue
                    if self._is_ready(p, last, last_action=last_action):
                        ready.append(p)
                        if last > 0 and p.seq == 1 and last >= 2 and self._action_rank(p.action) == 1:
                            last = 1
                        else:
                            last = p.seq
                        last_action = p.action
                    elif p.seq < last or (
                        p.seq == last
                        and self._action_rank(p.action) == 0
                        and str(last_action).upper().startswith("CLOSE")
                    ):
                        self._pending.remove(p)
                        logger.info(
                            "[WebhookSeq] drop stale symbol=%s bar=%s seq=%s action=%s last=%s",
                            symbol, bar, p.seq, p.action, state.last_seq,
                        )
                    else:
                        break

                if ready:
                    for p in ready:
                        if p not in self._pending:
                            continue
                        self._pending.remove(p)
                        self._mark_released(symbol, bar, p)
                        logger.info(
                            "[WebhookSeq] release symbol=%s bar_index=%s seq=%s action=%s cycle=%s",
                            symbol, bar, p.seq, p.action, self._bar_state(symbol, bar).cycle,
                        )
                        try:
                            fn(p.payload, p.fingerprint)
                        except Exception:
                            logger.exception("[WebhookSeq] dispatch failed seq=%s", p.seq)
                        released_n += 1
                    continue

                if not timed_out:
                    break

                missing = state.last_seq + 1 if state.last_seq > 0 else 1
                have = sorted(p.seq for p in bucket if p in self._pending)
                logger.warning(
                    "[WebhookSeq] gap timeout symbol=%s bar_index=%s missing_seq=%s have=%s age=%.2fs",
                    symbol, bar, missing, have, age,
                )
                self._alert_seq_gap(symbol, bar, missing, have, age)
                for p in sorted(
                    [x for x in bucket if x in self._pending],
                    key=self._sort_key,
                ):
                    self._pending.remove(p)
                    self._mark_released(symbol, bar, p)
                    logger.info(
                        "[WebhookSeq] force-release symbol=%s bar_index=%s seq=%s action=%s",
                        symbol, bar, p.seq, p.action,
                    )
                    try:
                        fn(p.payload, p.fingerprint)
                    except Exception:
                        logger.exception("[WebhookSeq] force dispatch failed seq=%s", p.seq)
                    released_n += 1
        return released_n

    def _alert_seq_gap(
        self,
        symbol: str,
        bar_index: int,
        missing_seq: int,
        have: list[int],
        age: float,
    ) -> None:
        try:
            from app.services.dingtalk_notify import push_dingtalk

            push_dingtalk(
                "Webhook 时序缺口",
                (
                    f"**symbol**: `{symbol}`\n\n"
                    f"**bar_index**: `{bar_index}`\n\n"
                    f"**缺失 seq**: `{missing_seq}`\n\n"
                    f"**已缓冲**: `{have}`\n\n"
                    f"**等待**: `{age:.1f}s` → 超时后按已有顺序强制释放"
                ),
            )
        except Exception as e:
            logger.warning("[WebhookSeq] gap alert failed: %s", e)


_gate: WebhookSeqGate | None = None
_gate_lock = threading.Lock()


def get_seq_gate() -> WebhookSeqGate:
    global _gate
    with _gate_lock:
        if _gate is None:
            _gate = WebhookSeqGate()
        return _gate


def reset_seq_gate_for_tests() -> WebhookSeqGate:
    """Replace singleton (unit tests)."""
    global _gate
    with _gate_lock:
        _gate = WebhookSeqGate()
        return _gate
