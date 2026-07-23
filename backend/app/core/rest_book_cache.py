"""Shared REST book cache — one fetch serves all symbols for a user.

Dual ETH+XAU supervisors previously each polled position/orders every 0.5s,
doubling Binance IP weight and triggering -1003. Cache merges:
  • positions: one futures_position_information() (all symbols)
  • open orders: one futures_get_open_orders() (all symbols)
  • algo stops: one refresh covering configured trading symbols

TTL is short so live trading stays fresh; user-data WS should invalidate on fills.
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
    k = _key(exchange, user_id)
    with _lock:
        _pos.pop(k, None)
        _orders.pop(k, None)
        _algo.pop(k, None)
    if reason:
        logger.debug("rest_book_cache invalidate %s (%s)", k, reason)


def reset_for_tests() -> None:
    with _lock:
        _pos.clear()
        _orders.clear()
        _algo.clear()


def get_cached_position(
    *,
    exchange: str,
    user_id: int | str,
    symbol: str,
    fetch_all: Callable[[], list],
    ttl: float = POS_TTL_SEC,
) -> dict | None:
    """Return one symbol row from a shared all-position snapshot."""
    from app.core.ip_rest_cooldown import raise_if_cooling, remaining_sec

    k = _key(exchange, user_id)
    left = remaining_sec(exchange=exchange, user_id=user_id)
    if left > 0:
        with _lock:
            hit = _pos.get(k) or {}
            cached = (hit.get("by_symbol") or {}).get(symbol)
        if cached is not None:
            return cached
        raise_if_cooling(exchange=exchange, user_id=user_id, op="get_position")

    now = time.time()
    with _lock:
        hit = _pos.get(k) or {}
        if hit and (now - float(hit.get("fetched_at") or 0)) < ttl:
            return (hit.get("by_symbol") or {}).get(symbol)

    try:
        rows = list(fetch_all() or [])
    except Exception as e:
        try:
            from app.core.exchange_errors import parse_binance_error
            from app.core.ip_rest_cooldown import note_rate_limit

            meta = parse_binance_error(e)
            if meta.get("code") in (-1003, "-1003", 1003, "1003") or "Too many requests" in str(e):
                note_rate_limit(
                    exchange=exchange,
                    user_id=user_id,
                    cool_sec=90.0,
                    banned_until_ms=meta.get("banned_until_ms"),
                )
        except Exception:
            pass
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
    k = _key(exchange, user_id)
    now = time.time()
    with _lock:
        hit = _orders.get(k) or {}
        if hit and (now - float(hit.get("fetched_at") or 0)) < ttl:
            return list((hit.get("by_symbol") or {}).get(symbol) or [])

    try:
        rows = list(fetch_all() or [])
    except Exception:
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
    k = _key(exchange, user_id)
    now = time.time()
    with _lock:
        hit = _algo.get(k) or {}
        if hit and (now - float(hit.get("fetched_at") or 0)) < ttl:
            return list((hit.get("by_symbol") or {}).get(symbol) or [])

    try:
        by_sym = dict(fetch_for_symbols(list(symbols)) or {})
    except Exception:
        raise

    with _lock:
        _algo[k] = {"fetched_at": now, "by_symbol": by_sym}
    return list(by_sym.get(symbol) or [])
