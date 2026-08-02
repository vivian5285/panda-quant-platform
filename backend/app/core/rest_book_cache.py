"""Shared REST book cache — one fetch serves all symbols for a user.

Dual ETH+XAU+BNB supervisors each previously polled position/orders every 0.5s,
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

# REST budget is now very conservative (8-10/min). Cache TTLs are increased to match:
# - Sentinel poll at 120s → POS_TTL at least 80s
# - Order audit at 120s → ORDER_TTL at least 100s
# - Algo orders at 120s → ALGO_TTL at least 100s
# Longer TTLs drastically reduce REST hits while WS handles fills in real-time.
POS_TTL_SEC = 80.0    # was 60.0 — position snapshot stays valid 80s
ORDER_TTL_SEC = 100.0  # was 90.0 — open orders snapshot stays valid 100s
ALGO_TTL_SEC = 100.0   # was 90.0 — algo orders snapshot stays valid 100s

_lock = threading.RLock()
# key = f"{exchange}:{user_id}"
_pos: dict[str, dict[str, Any]] = {}
_orders: dict[str, dict[str, Any]] = {}
_algo: dict[str, dict[str, Any]] = {}
# In-flight fetch barriers — ETH+XAU must not double-hit the same all-account REST.
_pos_flight: dict[str, threading.Event] = {}
_orders_flight: dict[str, threading.Event] = {}
_algo_flight: dict[str, threading.Event] = {}


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
        _pos_flight.clear()
        _orders_flight.clear()
        _algo_flight.clear()


def _begin_flight(store: dict[str, threading.Event], k: str) -> tuple[bool, threading.Event]:
    """Return (is_leader, event). Followers wait on event then re-read cache."""
    with _lock:
        ev = store.get(k)
        if ev is not None:
            return False, ev
        ev = threading.Event()
        store[k] = ev
        return True, ev


def _end_flight(store: dict[str, threading.Event], k: str, ev: threading.Event) -> None:
    with _lock:
        if store.get(k) is ev:
            store.pop(k, None)
    ev.set()


def _cool_left(exchange: str, user_id: int | str) -> float:
    try:
        from app.core.ip_rest_cooldown import remaining_sec

        return float(remaining_sec(exchange=exchange, user_id=user_id) or 0)
    except Exception:
        return 0.0


def _note_limit_from_exc(exchange: str, user_id: int | str, exc: BaseException) -> None:
    try:
        from app.core.exchange_errors import is_rate_limit_error, parse_binance_error
        from app.core.rest_throttle_valve import note_rate_limit

        meta = parse_binance_error(exc)
        if is_rate_limit_error(exc, code=meta.get("code")):
            note_rate_limit(
                exchange=exchange,
                user_id=user_id,
                cool_sec=180.0,
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
    force_refresh: bool = False,
) -> dict | None:
    """Return one symbol row from a shared all-position snapshot.

    Args:
        force_refresh: bypass IP cool-down and serve fresh data. Use for
            critical operations like post-open verification where stale data
            could cause false failures.
    """
    from app.core.ip_rest_cooldown import raise_if_cooling

    k = _key(exchange, user_id)
    left = _cool_left(exchange, user_id)
    if left > 0 and not force_refresh:
        with _lock:
            hit = _pos.get(k)
            if hit is not None:
                # Last known snapshot (incl. symbol missing = flat). Never raise.
                return (hit.get("by_symbol") or {}).get(symbol)
        raise_if_cooling(exchange=exchange, user_id=user_id, op="get_position")

    now = time.time()
    with _lock:
        hit = _pos.get(k) or {}
        if hit and (now - float(hit.get("fetched_at") or 0)) < ttl and not force_refresh:
            return (hit.get("by_symbol") or {}).get(symbol)

    leader, ev = _begin_flight(_pos_flight, k)
    if not leader:
        ev.wait(timeout=8.0)
        with _lock:
            hit = _pos.get(k)
            if hit is not None:
                return (hit.get("by_symbol") or {}).get(symbol)
        raise_if_cooling(exchange=exchange, user_id=user_id, op="get_position")

    try:
        from app.core.rest_symbol_pace import wait_turn
        from app.core.rest_throttle_valve import ThrottleDenied, acquire_rest_permit

        # Shared all-account endpoint — pace by user, not per-symbol.
        wait_turn(exchange=exchange, user_id=user_id, symbol="_all_positions")
        try:
            acquire_rest_permit(
                exchange=exchange, user_id=user_id, op="get_position",
            )
        except ThrottleDenied as td:
            if force_refresh:
                # Critical post-open verify: ignore throttle, proceed to fetch anyway.
                # Log only once to avoid log spam during throttle storm.
                logger.warning(
                    "get_position throttle denied + force_refresh — bypassing throttle to fetch (%s)",
                    str(td)[:160],
                )
            else:
                with _lock:
                    hit = _pos.get(k)
                    if hit is not None:
                        logger.warning(
                            "get_position throttle denied — serving stale (%s)",
                            str(td)[:160],
                        )
                        return (hit.get("by_symbol") or {}).get(symbol)
                raise_if_cooling(exchange=exchange, user_id=user_id, op="get_position")
                raise
        # Continue to fetch data (force_refresh bypasses the raise above)
        rows = list(fetch_all() or [])
        by_sym: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "")
            if sym:
                by_sym[sym] = row
        with _lock:
            _pos[k] = {"fetched_at": time.time(), "by_symbol": by_sym}
        return by_sym.get(symbol)
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
    finally:
        _end_flight(_pos_flight, k, ev)


def get_cached_open_orders(
    *,
    exchange: str,
    user_id: int | str,
    symbol: str,
    fetch_all: Callable[[], list],
    ttl: float = ORDER_TTL_SEC,
    force_refresh: bool = False,
) -> list[dict]:
    """Return open orders for one symbol from a shared all-orders snapshot.

    Args:
        force_refresh: bypass IP cool-down and serve fresh data. Use for
            critical operations like post-place verification.
    """
    from app.core.ip_rest_cooldown import raise_if_cooling

    k = _key(exchange, user_id)
    left = _cool_left(exchange, user_id)
    if left > 0 and not force_refresh:
        with _lock:
            hit = _orders.get(k)
            if hit is not None:
                return list((hit.get("by_symbol") or {}).get(symbol) or [])
        # No snapshot yet under cool-down: empty book (callers treat -1/unknown separately)
        return []

    now = time.time()
    with _lock:
        hit = _orders.get(k) or {}
        if hit and (now - float(hit.get("fetched_at") or 0)) < ttl and not force_refresh:
            return list((hit.get("by_symbol") or {}).get(symbol) or [])

    leader, ev = _begin_flight(_orders_flight, k)
    if not leader:
        ev.wait(timeout=8.0)
        with _lock:
            hit = _orders.get(k)
            if hit is not None:
                return list((hit.get("by_symbol") or {}).get(symbol) or [])
        return []

    try:
        from app.core.rest_symbol_pace import wait_turn
        from app.core.rest_throttle_valve import ThrottleDenied, acquire_rest_permit

        wait_turn(exchange=exchange, user_id=user_id, symbol="_all_orders")
        try:
            acquire_rest_permit(
                exchange=exchange, user_id=user_id, op="get_open_orders",
            )
        except ThrottleDenied as td:
            if force_refresh:
                # Critical post-place verify: ignore throttle, proceed to fetch anyway.
                logger.warning(
                    "get_open_orders throttle denied + force_refresh — bypassing throttle to fetch (%s)",
                    str(td)[:160],
                )
            else:
                with _lock:
                    hit = _orders.get(k)
                    if hit is not None:
                        logger.warning(
                            "get_open_orders throttle denied — serving stale (%s)",
                            str(td)[:160],
                        )
                        return list((hit.get("by_symbol") or {}).get(symbol) or [])
                return []
        # Continue to fetch data (force_refresh bypasses the return [] above)
        rows = list(fetch_all() or [])
        by_sym: dict[str, list[dict]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "")
            if not sym:
                continue
            by_sym.setdefault(sym, []).append(row)
        with _lock:
            _orders[k] = {"fetched_at": time.time(), "by_symbol": by_sym}
        return list(by_sym.get(symbol) or [])
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
    finally:
        _end_flight(_orders_flight, k, ev)


def get_cached_algo_orders(
    *,
    exchange: str,
    user_id: int | str,
    symbol: str,
    fetch_for_symbols: Callable[[list[str]], dict[str, list]],
    symbols: list[str],
    ttl: float = ALGO_TTL_SEC,
    force_refresh: bool = False,
) -> list[dict]:
    """Refresh algo books for all configured symbols in one cache window."""
    k = _key(exchange, user_id)
    left = _cool_left(exchange, user_id)
    if left > 0 and not force_refresh:
        with _lock:
            hit = _algo.get(k)
            if hit is not None:
                return list((hit.get("by_symbol") or {}).get(symbol) or [])
        return []

    now = time.time()
    with _lock:
        hit = _algo.get(k) or {}
        if hit and (now - float(hit.get("fetched_at") or 0)) < ttl and not force_refresh:
            return list((hit.get("by_symbol") or {}).get(symbol) or [])

    leader, ev = _begin_flight(_algo_flight, k)
    if not leader:
        ev.wait(timeout=8.0)
        with _lock:
            hit = _algo.get(k)
            if hit is not None:
                return list((hit.get("by_symbol") or {}).get(symbol) or [])
        return []

    try:
        from app.core.rest_throttle_valve import ThrottleDenied, acquire_rest_permit

        try:
            acquire_rest_permit(
                exchange=exchange, user_id=user_id, op="get_algo_orders",
            )
        except ThrottleDenied as td:
            if force_refresh:
                # Critical post-place verify: ignore throttle, proceed to fetch anyway.
                logger.warning(
                    "get_algo_orders throttle denied + force_refresh — bypassing throttle to fetch (%s)",
                    str(td)[:160],
                )
            else:
                with _lock:
                    hit = _algo.get(k)
                    if hit is not None:
                        logger.warning(
                            "get_algo_orders throttle denied — serving stale (%s)",
                            str(td)[:160],
                        )
                        return list((hit.get("by_symbol") or {}).get(symbol) or [])
                return []
        # Continue to fetch data (force_refresh bypasses the return [] above)
        by_sym = dict(fetch_for_symbols(list(symbols)) or {})
        with _lock:
            _algo[k] = {"fetched_at": time.time(), "by_symbol": by_sym}
        return list(by_sym.get(symbol) or [])
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
    finally:
        _end_flight(_algo_flight, k, ev)
