"""Binance USDT-M user data stream — invalidate REST book cache on fills.

One listenKey WS per user_id. ORDER_TRADE_UPDATE / ACCOUNT_UPDATE bump the
shared rest_book_cache so dual-symbol supervisors do not need 0.5s REST polls
to discover TP fills or flat events.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

_lock = threading.RLock()
# user_id -> runtime state
_streams: dict[int, dict[str, Any]] = {}


def ensure_binance_user_stream(
    *,
    user_id: int,
    client: Any,
    on_event: Callable[[dict], None] | None = None,
) -> None:
    """Idempotent: start private WS once per user."""
    uid = int(user_id)
    with _lock:
        st = _streams.get(uid)
        if st and st.get("running"):
            if on_event and on_event not in st.get("listeners", []):
                st.setdefault("listeners", []).append(on_event)
            return
        st = {
            "running": True,
            "thread": None,
            "listeners": [on_event] if on_event else [],
            "client": client,
            "listen_key": None,
            "started_at": time.time(),
        }
        _streams[uid] = st

    t = threading.Thread(
        target=_loop,
        args=(uid,),
        daemon=True,
        name=f"binance-userdata-u{uid}",
    )
    st["thread"] = t
    t.start()


def stop_binance_user_stream(user_id: int) -> None:
    uid = int(user_id)
    with _lock:
        st = _streams.get(uid)
        if not st:
            return
        st["running"] = False


def _loop(user_id: int) -> None:
    try:
        import websocket
    except ImportError:
        logger.warning("[User %s] websocket-client missing; user stream disabled", user_id)
        with _lock:
            st = _streams.get(user_id) or {}
            st["running"] = False
        return

    from app.core.rest_book_cache import invalidate
    from app.core.ws_reconnect import sleep_ws_reconnect

    attempt = 0
    while True:
        with _lock:
            st = _streams.get(user_id) or {}
            if not st.get("running"):
                return
            client = st.get("client")
        if client is None:
            return

        listen_key = _create_listen_key(client)
        if not listen_key:
            sleep_ws_reconnect(attempt)
            attempt += 1
            continue

        with _lock:
            st["listen_key"] = listen_key

        url = f"wss://fstream.binance.com/ws/{listen_key}"
        keepalive_stop = threading.Event()

        def _keepalive():
            while not keepalive_stop.wait(30 * 60):
                try:
                    client.client.futures_stream_keepalive(listenKey=listen_key)
                except Exception as exc:
                    logger.debug("[User %s] listenKey keepalive: %s", user_id, exc)

        ka = threading.Thread(target=_keepalive, daemon=True, name=f"binance-lk-u{user_id}")
        ka.start()

        def on_message(_ws, message):
            try:
                data = json.loads(message)
            except Exception:
                return
            et = str(data.get("e") or data.get("eventType") or "")
            if et in ("ORDER_TRADE_UPDATE", "ACCOUNT_UPDATE", "listenKeyExpired", "CONDITIONAL_ORDER_TRIGGER"):
                invalidate("binance", user_id, reason=et or "user_stream")
            if et == "listenKeyExpired":
                try:
                    _ws.close()
                except Exception:
                    pass
            with _lock:
                listeners = list((_streams.get(user_id) or {}).get("listeners") or [])
            for fn in listeners:
                try:
                    fn(data)
                except Exception:
                    pass

        def on_error(_ws, error):
            logger.warning("[User %s] user-data WS error: %s", user_id, error)

        def on_close(_ws, code, msg):
            logger.warning("[User %s] user-data WS closed: %s %s", user_id, code, msg)

        try:
            ws_app = websocket.WebSocketApp(
                url, on_message=on_message, on_error=on_error, on_close=on_close,
            )
            ws_app.run_forever(ping_interval=180, ping_timeout=30)
            attempt = 0
        except Exception as exc:
            logger.error("[User %s] user-data WS loop: %s", user_id, exc)
        finally:
            keepalive_stop.set()

        with _lock:
            if not (_streams.get(user_id) or {}).get("running"):
                return
        sleep_ws_reconnect(attempt)
        attempt += 1


def _create_listen_key(client: Any) -> str | None:
    try:
        # python-binance helpers
        if hasattr(client.client, "futures_stream_get_listen_key"):
            raw = client.client.futures_stream_get_listen_key()
            if isinstance(raw, dict):
                return str(raw.get("listenKey") or "") or None
            return str(raw or "") or None
        raw = client.client._request_futures_api("post", "listenKey", signed=False, data={})
        if isinstance(raw, dict):
            return str(raw.get("listenKey") or "") or None
    except Exception as exc:
        logger.warning("[User %s] create listenKey failed: %s", getattr(client, "user_id", "?"), exc)
    return None
