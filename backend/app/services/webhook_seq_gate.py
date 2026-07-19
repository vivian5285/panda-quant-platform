"""TradingView bar_index + seq reorder gate.

Canonical same-bar rule (VPS 铁律 · 四所统一):
  When OPEN and CLOSE_* arrive on the same bar (often the same second),
  ALWAYS execute CLOSE first, then OPEN last — final live state must be OPEN.

V1.6.10 Pine may emit OPEN seq=1 and CLOSE_PROTECT seq=2 (open seq < close seq).
Never sort by seq alone for that pair — that caused live open-then-instant-flat.

Sort key: (close-before-open, seq ASC, enqueued_at ASC).
Companion hold: lone OPEN waits WEBHOOK_SEQ_WAIT_SEC for a possible CLOSE.

If a higher seq arrives before a missing lower seq, hold WEBHOOK_SEQ_WAIT_SEC,
then alert and force-release in close-before-open order.
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
        """0=CLOSE (first), 1=OPEN/LONG/SHORT (last), 2=other."""
        a = str(action or "").upper()
        if a.startswith("CLOSE"):
            return 0
        if a in ("LONG", "SHORT", "BUY", "SELL") or a.startswith("OPEN"):
            return 1
        return 2

    def _sort_key(self, p: _Pending) -> tuple:
        """CLOSE before OPEN always — seq is secondary (V1.6.10 OPEN=1 CLOSE=2)."""
        return (self._action_rank(p.action), p.seq, p.enqueued_at)

    @classmethod
    def _bucket_has_close(cls, bucket: list[_Pending]) -> bool:
        return any(cls._action_rank(p.action) == 0 for p in bucket)

    @classmethod
    def _bucket_has_open(cls, bucket: list[_Pending]) -> bool:
        return any(cls._action_rank(p.action) == 1 for p in bucket)

    def _hold_lone_open(
        self,
        bucket: list[_Pending],
        *,
        timed_out: bool,
        state: _BarState,
    ) -> bool:
        """Pause briefly so same-second CLOSE can join before the first OPEN on a bar."""
        if timed_out:
            return False
        # Already released something on this bar (e.g. CLOSE→OPEN unit done) —
        # do not block a trailing OPEN (1-2-1 cycle).
        if state.last_seq > 0 or str(state.last_action or "").strip():
            return False
        return self._bucket_has_open(bucket) and not self._bucket_has_close(bucket)

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
        # Legacy recycle: OPEN seq:1 after CLOSE seq:2 (or higher)
        if item.seq == 1 and last_seq >= 2 and self._action_rank(item.action) == 1:
            return True
        # Trailing OPEN seq:1 after same-bar CLOSE→OPEN unit already ran (1-2-1 third leg)
        if (
            item.seq == 1
            and last_seq == 1
            and self._action_rank(item.action) == 1
            and self._action_rank(last_action) == 1
        ):
            return True
        return False

    def _release_items(self, fn: DispatchFn, symbol: str, bar: int, items: list[_Pending]) -> int:
        released_n = 0
        for p in items:
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
        return released_n

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
                # CLOSE before OPEN, then seq, then arrival
                bucket.sort(key=self._sort_key)
                state = self._bar_state(symbol, bar)
                age = now - min(p.enqueued_at for p in bucket)
                timed_out = force or age >= wait

                # Drop already-released fingerprints
                for p in list(bucket):
                    if p.fingerprint in state.released_fps:
                        if p in self._pending:
                            self._pending.remove(p)
                        bucket.remove(p)
                if not bucket:
                    continue

                # Iron rule: never fire the first OPEN alone while CLOSE may still arrive
                if self._hold_lone_open(bucket, timed_out=timed_out, state=state):
                    logger.info(
                        "[WebhookSeq] hold OPEN for CLOSE companion symbol=%s bar=%s "
                        "age=%.2fs wait=%.2fs actions=%s",
                        symbol,
                        bar,
                        age,
                        wait,
                        [f"{p.action}:{p.seq}" for p in bucket],
                    )
                    break

                has_close = self._bucket_has_close(bucket)
                has_open = self._bucket_has_open(bucket)

                # Same-bar OPEN+CLOSE (any seq order): flush CLOSE→OPEN as a unit
                if has_close and has_open:
                    logger.info(
                        "[WebhookSeq] same-bar CLOSE→OPEN unit symbol=%s bar=%s order=%s",
                        symbol,
                        bar,
                        [f"{p.action}:{p.seq}" for p in bucket],
                    )
                    released_n += self._release_items(fn, symbol, bar, bucket)
                    continue

                ready: list[_Pending] = []
                last = state.last_seq
                last_action = state.last_action
                for p in bucket:
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
                        if p in self._pending:
                            self._pending.remove(p)
                        logger.info(
                            "[WebhookSeq] drop stale symbol=%s bar=%s seq=%s action=%s last=%s",
                            symbol, bar, p.seq, p.action, state.last_seq,
                        )
                    else:
                        break

                if ready:
                    released_n += self._release_items(fn, symbol, bar, ready)
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
                force_items = sorted(
                    [x for x in bucket if x in self._pending],
                    key=self._sort_key,
                )
                released_n += self._release_items(fn, symbol, bar, force_items)
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
                    f"**等待**: `{age:.1f}s` → 超时后按先平后开强制释放"
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
        old = _gate
        if old is not None:
            with old._lock:
                if old._timer:
                    old._timer.cancel()
                    old._timer = None
                old._pending.clear()
        _gate = WebhookSeqGate()
        return _gate
