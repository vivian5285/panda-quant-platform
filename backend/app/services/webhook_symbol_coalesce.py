"""Per-symbol TV webhook coalesce — checklist §消息顺序处理.

Cache 1~2s per symbol (default 1.0s), then execute:
  1. At most one CLOSE_* (idempotent flat)
  2. Latest LONG/SHORT (open path still force-flats)

Same-window rule: ALWAYS close-then-open (never ignore open when close present).
Works with or without bar_index/seq — all exchanges share this ingress.
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
    """Buffer per symbol → priority flush (CLOSE once, then latest OPEN)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._buckets: dict[str, _SymbolBucket] = {}
        self._dispatch: DispatchFn | None = None

    def set_dispatch(self, fn: DispatchFn) -> None:
        self._dispatch = fn

    def pending_depth(self) -> int:
        with self._lock:
            return sum(len(b.messages) for b in self._buckets.values())

    def window_sec(self) -> float:
        raw = float(getattr(get_settings(), "WEBHOOK_COALESCE_SEC", 1.0) or 1.0)
        return max(1.0, min(2.0, raw))

    def submit(
        self,
        payload: dict,
        fingerprint: str,
        *,
        dispatch: DispatchFn | None = None,
    ) -> str:
        """Enqueue into symbol window. Returns buffered | coalesced_drop | flushed."""
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
        # Prefer QUICK over RSI if both present; else earliest exit
        exits.sort(
            key=lambda m: (
                0 if m.action == "CLOSE_QUICK_EXIT" else 1,
                m.enqueued_at,
            )
        )
        # Latest open by enqueue time
        entries.sort(key=lambda m: m.enqueued_at)

        plan: list[_CachedMsg] = []
        if exits:
            plan.append(exits[0])
        if entries:
            plan.append(entries[-1])

        logger.info(
            "[WebhookCoalesce] flush symbol=%s raw=%s plan=%s",
            symbol,
            [f"{m.action}" for m in msgs],
            [f"{m.action}" for m in plan],
        )

        released = 0
        for m in plan:
            try:
                fn(m.payload, m.fingerprint)
                released += 1
            except Exception:
                logger.exception(
                    "[WebhookCoalesce] dispatch failed symbol=%s action=%s",
                    symbol, m.action,
                )
        return released


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
            with old._lock:
                for b in old._buckets.values():
                    if b.timer:
                        b.timer.cancel()
                old._buckets.clear()
        _coalesce = WebhookSymbolCoalesce()
        return _coalesce
