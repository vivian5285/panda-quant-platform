"""Shared REST book cache — one fetch serves all symbols for a user.

Dual ETH+XAU supervisors previously each polled position/orders every 0.5s,
doubling Binance IP weight and triggering -1003. Cache merges:
  • positions: one futures_position_information() (all symbols)
  • open orders: one futures_get_open_orders() (all symbols)
  • algo stops: one refresh covering configured trading symbols

TTL is short so live trading stays fresh; user-data WS should invalidate on fills.

Critical: during IP cool-down (-1003), ALWAYS serve last snapshot (even past TTL)
and NEVER hit REST. Empty/missing symbol in a known snapshot means flat/empty book
— do not raise cool-down errors every breath tick (that was the 1s log storm).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

POS_TTL_SEC = 3.0
ORDER_TTL_SEC = 5.0
ALGO_TTL_SEC = 5.0

_lock = threading.RLock()
# key = f"{exchange}:{user_id}"
_pos: dict[str, dict[str, Any]] = {}
_orders: dict[str, dict[str, Any]] = {}
_algo: dict[str, dict[str, Any]] = {}


def _key(exchange: str, user_id: int | str) -> str:
    return f"{(exchange or 'binance').lower()}:{int(user_id)}"


def invalidate(exchange: str, user_id: int | str, *, reason: str = "") -> None:
    """Expire TTL so the next non-cool fetch refreshes — keep last snapshot.

    Hard-delete under -1003 caused every breath tick to raise cool-down errors
    (no cache → raise_if_cooling → 1s log/DingTalk storm).
    """
    k = _key(exchange, user_id)
    with _lock:
        for store in (_pos, _orders, _algo):
            hit = store.get(k)
            if isinstance(hit, dict):
                hit["fetched_at"] = 0.0
            else:
                store.pop(k, None)
    if reason:
        logger.debug("rest_book_cache invalidate %s (%s)", k, reason)


def reset_for_tests() -> None:
    with _lock:
        _pos.clear()
        _orders.clear()
        _algo.clear()


def _cool_left(exchange: str, user_id: int | str) -> float:
    try:
        from app.core.ip_rest_cooldown import remaining_sec

        return float(remaining_sec(exchange=exchange, user_id=user_id) or 0)
    except Exception:
        return 0.0


def _note_limit_from_exc(exchange: str, user_id: int | str, exc: BaseException) -> None:
    try:
        from app.core.exchange_errors import parse_binance_error
        from app.core.ip_rest_cooldown import note_rate_limit

        meta = parse_binance_error(exc)
        if meta.get("code") in (-1003, "-1003", 1003, "1003") or "Too many requests" in str(exc):
            note_rate_limit(
                exchange=exchange,
                user_id=user_id,
                cool_sec=90.0,
                banned_until_ms=meta.get("banned_until_ms"),
            )
    except Exception:
        pass


def get_cached_position(
    *,
    exchange: str,
    user_id: int | str,
    symbol: str,
    fetch_all: Callable[[], list],
    ttl: float = POS_TTL_SEC,
) -> dict | None:
    """Return one symbol row from a shared all-position snapshot."""
    from app.core.ip_rest_cooldown import raise_if_cooling

    k = _key(exchange, user_id)
    left = _cool_left(exchange, user_id)
    if left > 0:
        with _lock:
            hit = _pos.get(k)
            if hit is not None:
                # Last known snapshot (incl. symbol missing = flat). Never raise.
                return (hit.get("by_symbol") or {}).get(symbol)
        raise_if_cooling(exchange=exchange, user_id=user_id, op="get_position")

    now = time.time()
    with _lock:
        hit = _pos.get(k) or {}
        if hit and (now - float(hit.get("fetched_at") or 0)) < ttl:
            return (hit.get("by_symbol") or {}).get(symbol)

    try:
        rows = list(fetch_all() or [])
    except Exception as e:
        _note_limit_from_exc(exchange, user_id, e)
        # Prefer stale over raise when we still have a snapshot
        with _lock:
            hit = _pos.get(k)
            if hit is not None:
                logger.warning(
                    "get_position fetch failed — serving stale (%s)",
                    str(e)[:160],
                )
                return (hit.get("by_symbol") or {}).get(symbol)
        raise

    by_sym: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "")
        if sym:
            by_sym[sym] = row
    with _lock:
        _pos[k] = {"fetched_at": now, "by_symbol": by_sym}
    return by_sym.get(symbol)


def get_cached_open_orders(
    *,
    exchange: str,
    user_id: int | str,
    symbol: str,
    fetch_all: Callable[[], list],
    ttl: float = ORDER_TTL_SEC,
) -> list[dict]:
    """Return open orders for one symbol from a shared all-orders snapshot."""
    from app.core.ip_rest_cooldown import raise_if_cooling

    k = _key(exchange, user_id)
    left = _cool_left(exchange, user_id)
    if left > 0:
        with _lock:
            hit = _orders.get(k)
            if hit is not None:
                return list((hit.get("by_symbol") or {}).get(symbol) or [])
        raise_if_cooling(exchange=exchange, user_id=user_id, op="get_open_orders")

    now = time.time()
    with _lock:
        hit = _orders.get(k) or {}
        if hit and (now - float(hit.get("fetched_at") or 0)) < ttl:
            return list((hit.get("by_symbol") or {}).get(symbol) or [])

    try:
        rows = list(fetch_all() or [])
    except Exception as e:
        _note_limit_from_exc(exchange, user_id, e)
        with _lock:
            hit = _orders.get(k)
            if hit is not None:
                logger.warning(
                    "get_open_orders fetch failed — serving stale (%s)",
                    str(e)[:160],
                )
                return list((hit.get("by_symbol") or {}).get(symbol) or [])
        raise

    by_sym: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "")
        if not sym:
            continue
        by_sym.setdefault(sym, []).append(row)
    with _lock:
        _orders[k] = {"fetched_at": now, "by_symbol": by_sym}
    return list(by_sym.get(symbol) or [])


def get_cached_algo_orders(
    *,
    exchange: str,
    user_id: int | str,
    symbol: str,
    fetch_for_symbols: Callable[[list[str]], dict[str, list]],
    symbols: list[str],
    ttl: float = ALGO_TTL_SEC,
) -> list[dict]:
    """Refresh algo books for all configured symbols in one cache window."""
    from app.core.ip_rest_cooldown import raise_if_cooling

    k = _key(exchange, user_id)
    left = _cool_left(exchange, user_id)
    if left > 0:
        with _lock:
            hit = _algo.get(k)
            if hit is not None:
                return list((hit.get("by_symbol") or {}).get(symbol) or [])
        raise_if_cooling(exchange=exchange, user_id=user_id, op="get_algo_orders")

    now = time.time()
    with _lock:
        hit = _algo.get(k) or {}
        if hit and (now - float(hit.get("fetched_at") or 0)) < ttl:
            return list((hit.get("by_symbol") or {}).get(symbol) or [])

    try:
        by_sym = dict(fetch_for_symbols(list(symbols)) or {})
    except Exception as e:
        _note_limit_from_exc(exchange, user_id, e)
        with _lock:
            hit = _algo.get(k)
            if hit is not None:
                logger.warning(
                    "get_algo_orders fetch failed — serving stale (%s)",
                    str(e)[:160],
                )
                return list((hit.get("by_symbol") or {}).get(symbol) or [])
        raise

    with _lock:
        _algo[k] = {"fetched_at": now, "by_symbol": by_sym}
    return list(by_sym.get(symbol) or [])
