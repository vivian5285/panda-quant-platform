"""Local pending-order tags — last line of defense against duplicate place storms.

Rule (non-negotiable): if a local tag is in-flight for this kind/symbol, NEVER place
again — even when exchange open-orders returns empty / errors / cool-down stale [].

Historical failure mode: unreadable book → treat as "missing" → re-place → 50+
identical LIMITs → live account blow-up.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Hard TTL: even if release is missed, tag auto-expires (must be > typical place RTT)
DEFAULT_TAG_TTL_SEC = 120.0
REENTRY_TAG_TTL_SEC = 330.0  # > LIMIT_TTL 300s
TP_TAG_TTL_SEC = 90.0
STOP_TAG_TTL_SEC = 90.0


@dataclass
class PendingTag:
    tag: str
    kind: str
    symbol: str
    created_at: float
    ttl_sec: float
    oid: Any = None
    client_order_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def expired(self, now: float | None = None) -> bool:
        t = float(now if now is not None else time.time())
        return t >= float(self.created_at) + float(self.ttl_sec)


class PendingOrderRegistry:
    """Thread-safe per-supervisor registry of in-flight place attempts."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tags: dict[str, PendingTag] = {}

    def _purge_expired_unlocked(self) -> None:
        now = time.time()
        dead = [k for k, v in self._tags.items() if v.expired(now)]
        for k in dead:
            self._tags.pop(k, None)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            self._purge_expired_unlocked()
            return [
                {
                    "tag": t.tag,
                    "kind": t.kind,
                    "symbol": t.symbol,
                    "oid": t.oid,
                    "client_order_id": t.client_order_id,
                    "age_sec": round(time.time() - t.created_at, 2),
                    "ttl_sec": t.ttl_sec,
                    **(t.meta or {}),
                }
                for t in self._tags.values()
            ]

    def has_active(self, tag: str) -> bool:
        with self._lock:
            self._purge_expired_unlocked()
            t = self._tags.get(tag)
            return t is not None and not t.expired()

    def active_by_kind(self, kind: str, *, symbol: str | None = None) -> PendingTag | None:
        with self._lock:
            self._purge_expired_unlocked()
            kind_u = str(kind or "").lower()
            for t in self._tags.values():
                if t.kind != kind_u:
                    continue
                if symbol and str(t.symbol).upper() != str(symbol).upper():
                    continue
                if not t.expired():
                    return t
            return None

    def try_acquire(
        self,
        tag: str,
        *,
        kind: str,
        symbol: str,
        ttl_sec: float = DEFAULT_TAG_TTL_SEC,
        client_order_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Return (ok, reason). ok=False → MUST NOT place."""
        tag = str(tag or "").strip()
        if not tag:
            return False, "empty_tag"
        with self._lock:
            self._purge_expired_unlocked()
            cur = self._tags.get(tag)
            if cur is not None and not cur.expired():
                return False, "local_tag_inflight"
            # Also block same kind+symbol for exclusive kinds
            kind_u = str(kind or "").lower()
            if kind_u in ("reentry", "hard", "radar"):
                for t in self._tags.values():
                    if t.kind != kind_u:
                        continue
                    if str(t.symbol).upper() != str(symbol or "").upper():
                        continue
                    if not t.expired():
                        return False, f"local_{kind_u}_inflight"
            self._tags[tag] = PendingTag(
                tag=tag,
                kind=kind_u,
                symbol=str(symbol or ""),
                created_at=time.time(),
                ttl_sec=float(ttl_sec),
                client_order_id=client_order_id,
                meta=dict(meta or {}),
            )
            return True, "acquired"

    def mark_oid(self, tag: str, oid: Any) -> None:
        with self._lock:
            t = self._tags.get(tag)
            if t is not None:
                t.oid = oid

    def release(self, tag: str, *, reason: str = "done") -> None:
        with self._lock:
            if tag in self._tags:
                logger.info("pending_tag release %s reason=%s", tag, reason)
                self._tags.pop(tag, None)

    def release_kind(self, kind: str, *, symbol: str | None = None) -> int:
        with self._lock:
            kind_u = str(kind or "").lower()
            dead = []
            for k, t in self._tags.items():
                if t.kind != kind_u:
                    continue
                if symbol and str(t.symbol).upper() != str(symbol).upper():
                    continue
                dead.append(k)
            for k in dead:
                self._tags.pop(k, None)
            return len(dead)

    def clear_all(self, *, reason: str = "flat") -> int:
        with self._lock:
            n = len(self._tags)
            self._tags.clear()
            if n:
                logger.info("pending_tag clear_all n=%s reason=%s", n, reason)
            return n


def make_client_order_id(prefix: str, *parts: Any) -> str:
    """Binance futures newClientOrderId: ≤36 chars, [A-Za-z0-9_-:.]."""
    raw = f"{prefix}" + "".join(str(p) for p in parts if p is not None)
    # Strip illegal chars
    cleaned = "".join(c for c in raw if c.isalnum() or c in "_-.:")
    if len(cleaned) > 28:
        cleaned = cleaned[:28]
    suffix = uuid.uuid4().hex[:8]
    out = f"{cleaned}{suffix}"
    return out[:36]


def reentry_tag(user_id: Any, symbol: str, attempt: int) -> str:
    return f"reentry:{user_id}:{str(symbol).upper()}:{int(attempt)}"


def tp_tag(user_id: Any, symbol: str, label: str, price: float) -> str:
    px = f"{float(price):.4f}".rstrip("0").rstrip(".")
    return f"tp:{user_id}:{str(symbol).upper()}:{label}:{px}"


def hard_tag(user_id: Any, symbol: str) -> str:
    return f"hard:{user_id}:{str(symbol).upper()}"


def radar_tag(user_id: Any, symbol: str) -> str:
    return f"radar:{user_id}:{str(symbol).upper()}"
