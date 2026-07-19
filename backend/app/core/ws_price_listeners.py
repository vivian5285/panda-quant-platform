"""Shared WS mark-price cache listener fan-out for all exchange clients."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

PriceListener = Callable[[str, float], None]


def ensure_price_listener_state(client: Any) -> None:
    if not hasattr(client, "_price_listeners"):
        client._price_listeners = []
    if not hasattr(client, "_price_listener_lock"):
        client._price_listener_lock = threading.Lock()


def register_price_listener(client: Any, callback: PriceListener) -> None:
    """Register callback(symbol, price) fired on every WS mark update."""
    ensure_price_listener_state(client)
    with client._price_listener_lock:
        if callback not in client._price_listeners:
            client._price_listeners.append(callback)


def unregister_price_listener(client: Any, callback: PriceListener) -> None:
    ensure_price_listener_state(client)
    with client._price_listener_lock:
        client._price_listeners = [c for c in client._price_listeners if c is not callback]


def notify_price_listeners(client: Any, symbol: str, price: float) -> None:
    listeners = getattr(client, "_price_listeners", None) or []
    if not listeners:
        return
    px = float(price or 0)
    if px <= 0:
        return
    for cb in list(listeners):
        try:
            cb(str(symbol), px)
        except Exception as exc:
            logger.debug("[WSPrice] listener error: %s", exc)
