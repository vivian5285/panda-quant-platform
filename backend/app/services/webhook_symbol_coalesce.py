"""Per-symbol TV webhook coalesce — whitepaper §二 15s OPEN/CLOSE iron rule.

Window default 15s. Rules (no TV timestamp comparison):
  - CLOSE first, OPEN within window → flush CLOSE once then latest OPEN
  - OPEN first (buffered or already dispatched), CLOSE within 15s of OPEN → discard CLOSE
  - CLOSE >15s after last OPEN → normal independent close
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

CLOSE_ACTIONS = frozenset({"CLOSE_QUICK_EXIT", "CLOSE_RSI_EXIT"})
ENTRY_ACTIONS = frozenset({"LONG", "SHORT"})
# Whitepaper: 15s window for same-K OPEN/CLOSE pairing / discard
COALESCE_WINDOW_MAX_SEC = 15.0
COALESCE_WINDOW_MIN_SEC = 0.5
POST_OPEN_CLOSE_DISCARD_SEC = 15.0


@dataclass
class _CachedMsg:
    payload: dict
    fingerprint: str
    action: str
    enqueued_at: float = field(default_factory=time.time)


@dataclass
class _SymbolBucket:
    messages: list[_CachedMsg] = field(default_factory=list)
    first_seen: float = field(default_factory=time.time)
    fingerprints: set[str] = field(default_factory=set)
    timer: threading.Timer | None = None


class WebhookSymbolCoalesce:
    """Buffer per symbol → priority flush with post-OPEN CLOSE discard."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._buckets: dict[str, _SymbolBucket] = {}
        self._dispatch: DispatchFn | None = None
        # Wall-clock of last successfully dispatched OPEN per symbol
        self._last_open_dispatched_at: dict[str, float] = {}

    def set_dispatch(self, fn: DispatchFn) -> None:
        self._dispatch = fn

    def pending_depth(self) -> int:
        with self._lock:
            return sum(len(b.messages) for b in self._buckets.values())

    def window_sec(self) -> float:
        raw = float(getattr(get_settings(), "WEBHOOK_COALESCE_SEC", 15.0) or 15.0)
        return max(COALESCE_WINDOW_MIN_SEC, min(COALESCE_WINDOW_MAX_SEC, raw))

    def discard_window_sec(self) -> float:
        return POST_OPEN_CLOSE_DISCARD_SEC

    def last_open_age_sec(self, symbol: str) -> float | None:
        with self._lock:
            ts = self._last_open_dispatched_at.get(symbol)
            if ts is None:
                return None
            return time.time() - ts

    def submit(
        self,
        payload: dict,
        fingerprint: str,
        *,
        dispatch: DispatchFn | None = None,
    ) -> str:
        """Enqueue into symbol window. Returns buffered | coalesced_drop | discarded_post_open | flushed."""
        fn = dispatch or self._dispatch
        if dispatch is not None:
            self._dispatch = dispatch
        if fn is None:
            raise RuntimeError("WebhookSymbolCoalesce dispatch callback not set")

        from app.core.symbol_registry import extract_payload_symbol

        symbol = extract_payload_symbol(payload, require=False) or "UNKNOWN"
        action = str(payload.get("action", "")).upper()
        now = time.time()

        with self._lock:
            # OPEN already executed → CLOSE within 15s is discarded (whitepaper)
            if action in CLOSE_ACTIONS:
                last_open = self._last_open_dispatched_at.get(symbol)
                if last_open is not None and (now - last_open) < self.discard_window_sec():
                    logger.info(
                        "[WebhookCoalesce] discarded_post_open symbol=%s action=%s age=%.2fs",
                        symbol,
                        action,
                        now - last_open,
                    )
                    return "discarded_post_open"

            bucket = self._buckets.get(symbol)
            if bucket is None:
                bucket = _SymbolBucket(first_seen=now)
                self._buckets[symbol] = bucket
                self._arm_timer_locked(symbol, bucket)

            # Same fingerprint already in this window → merge
            if fingerprint in bucket.fingerprints:
                logger.info(
                    "[WebhookCoalesce] drop in-window dup symbol=%s action=%s fp=%s",
                    symbol, action, fingerprint[:40],
                )
                return "coalesced_drop"

            # Same action already buffered → keep newest only (merge)
            if action in CLOSE_ACTIONS | ENTRY_ACTIONS:
                bucket.messages = [m for m in bucket.messages if m.action != action]

            bucket.messages.append(
                _CachedMsg(payload=payload, fingerprint=fingerprint, action=action)
            )
            bucket.fingerprints.add(fingerprint)
            logger.info(
                "[WebhookCoalesce] buffered symbol=%s action=%s depth=%s age=%.2fs window=%.2fs",
                symbol,
                action,
                len(bucket.messages),
                now - bucket.first_seen,
                self.window_sec(),
            )
            # If window already expired (clock skew / long lock), flush now
            if now - bucket.first_seen >= self.window_sec():
                self._flush_symbol_locked(symbol, fn)
                return "flushed"
            return "buffered"

    def flush_now(self, symbol: str | None = None) -> int:
        """Force flush (tests / shutdown)."""
        fn = self._dispatch
        if fn is None:
            return 0
        with self._lock:
            symbols = [symbol] if symbol else list(self._buckets.keys())
            n = 0
            for s in symbols:
                n += self._flush_symbol_locked(s, fn)
            return n

    def _arm_timer_locked(self, symbol: str, bucket: _SymbolBucket) -> None:
        if bucket.timer is not None:
            bucket.timer.cancel()
        delay = max(0.05, self.window_sec() - (time.time() - bucket.first_seen))
        t = threading.Timer(delay, self._on_timer, args=(symbol,))
        t.daemon = True
        bucket.timer = t
        t.start()

    def _on_timer(self, symbol: str) -> None:
        fn = self._dispatch
        if fn is None:
            return
        with self._lock:
            self._flush_symbol_locked(symbol, fn)

    def _flush_symbol_locked(self, symbol: str, fn: DispatchFn) -> int:
        bucket = self._buckets.pop(symbol, None)
        if bucket is None:
            return 0
        if bucket.timer is not None:
            bucket.timer.cancel()
            bucket.timer = None

        msgs = list(bucket.messages)
        if not msgs:
            return 0

        exits = [m for m in msgs if m.action in CLOSE_ACTIONS]
        entries = [m for m in msgs if m.action in ENTRY_ACTIONS]
        exits.sort(
            key=lambda m: (
                0 if m.action == "CLOSE_QUICK_EXIT" else 1,
                m.enqueued_at,
            )
        )
        entries.sort(key=lambda m: m.enqueued_at)

        plan: list[_CachedMsg] = []
        if exits and entries:
            first_exit = min(exits, key=lambda m: m.enqueued_at)
            first_entry = min(entries, key=lambda m: m.enqueued_at)
            if first_entry.enqueued_at <= first_exit.enqueued_at:
                # OPEN arrived first in window → discard CLOSE, keep latest OPEN
                plan.append(entries[-1])
                logger.info(
                    "[WebhookCoalesce] OPEN-first in window → discard CLOSE symbol=%s",
                    symbol,
                )
            else:
                # CLOSE first → flatten then open
                plan.append(exits[0])
                plan.append(entries[-1])
        elif exits:
            plan.append(exits[0])
        elif entries:
            plan.append(entries[-1])

        logger.info(
            "[WebhookCoalesce] flush symbol=%s raw=%s plan=%s",
            symbol,
            [f"{m.action}" for m in msgs],
            [f"{m.action}" for m in plan],
        )

        if exits and entries and len(plan) >= 2:
            self._notify_close_open_same_window(symbol, msgs, plan)

        released = 0
        for m in plan:
            try:
                fn(m.payload, m.fingerprint)
                released += 1
                if m.action in ENTRY_ACTIONS:
                    self._last_open_dispatched_at[symbol] = time.time()
            except Exception:
                logger.exception(
                    "[WebhookCoalesce] dispatch failed symbol=%s action=%s",
                    symbol, m.action,
                )
        return released

    @staticmethod
    def _notify_close_open_same_window(
        symbol: str,
        raw_msgs: list[_CachedMsg],
        plan: list[_CachedMsg],
    ) -> None:
        """DingTalk when CLOSE+OPEN share one coalesce window (CLOSE-first path)."""
        try:
            from app.services.alert_service import notify_system

            raw_actions = [m.action for m in raw_msgs]
            plan_actions = [m.action for m in plan]
            notify_system(
                "info",
                "COALESCE_WINDOW",
                "缓存窗口处理",
                (
                    f"检测到平仓+开仓同时到达，已按先平后开顺序执行 "
                    f"| symbol={symbol} raw={raw_actions} plan={plan_actions}"
                ),
                {
                    "symbol": symbol,
                    "raw_actions": raw_actions,
                    "plan_actions": plan_actions,
                },
            )
        except Exception:
            logger.exception(
                "[WebhookCoalesce] COALESCE_WINDOW notify failed symbol=%s",
                symbol,
            )


_coalesce: WebhookSymbolCoalesce | None = None
_coalesce_lock = threading.Lock()


def get_coalesce() -> WebhookSymbolCoalesce:
    global _coalesce
    with _coalesce_lock:
        if _coalesce is None:
            _coalesce = WebhookSymbolCoalesce()
        return _coalesce


def reset_coalesce_for_tests() -> WebhookSymbolCoalesce:
    global _coalesce
    with _coalesce_lock:
        old = _coalesce
        if old is not None:
            try:
                for b in list(old._buckets.values()):
                    if b.timer is not None:
                        b.timer.cancel()
            except Exception:
                pass
        _coalesce = WebhookSymbolCoalesce()
        return _coalesce
