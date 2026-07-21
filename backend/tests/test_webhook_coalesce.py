"""TV webhook symbol coalesce — CLOSE once then latest OPEN."""

import time
from unittest.mock import MagicMock

import pytest

from app.services.webhook_idempotency import compute_fingerprint, IDEMPOTENCY_TTL_SEC
from app.services.webhook_symbol_coalesce import (
    WebhookSymbolCoalesce,
    reset_coalesce_for_tests,
)


@pytest.fixture
def coalesce(monkeypatch):
    monkeypatch.setattr(
        "app.services.webhook_symbol_coalesce.get_settings",
        lambda: MagicMock(WEBHOOK_COALESCE_SEC=1.5),
    )
    c = reset_coalesce_for_tests()
    yield c
    c.flush_now()
    reset_coalesce_for_tests()


def _msg(action: str, symbol: str = "ETHUSDT", price: float = 3300.0, **extra):
    d = {"action": action, "symbol": symbol, "price": price, "token": "528586", **extra}
    return d, compute_fingerprint(d)


def test_coalesce_window_default_clamped():
    c = WebhookSymbolCoalesce()
    # default settings may vary; clamp is 1~2
    assert 1.0 <= c.window_sec() <= 2.0


def test_short_then_close_reorders_close_first(coalesce, monkeypatch):
    monkeypatch.setattr(
        "app.services.webhook_symbol_coalesce.get_settings",
        lambda: MagicMock(WEBHOOK_COALESCE_SEC=1.0),
    )
    released = []

    def capture(payload, fp):
        released.append(payload["action"])

    coalesce.set_dispatch(capture)
    # 乱序：先 SHORT 后 CLOSE
    coalesce.submit(*_msg("SHORT", price=3301), dispatch=capture)
    coalesce.submit(*_msg("CLOSE_QUICK_EXIT", price=3290, reason="rev"), dispatch=capture)
    coalesce.flush_now("ETHUSDT")

    assert released == ["CLOSE_QUICK_EXIT", "SHORT"]


def test_close_then_short_normal_order(coalesce):
    released = []
    coalesce.set_dispatch(lambda p, fp: released.append(p["action"]))
    coalesce.submit(*_msg("CLOSE_QUICK_EXIT", price=3290))
    coalesce.submit(*_msg("SHORT", price=3301))
    coalesce.flush_now("ETHUSDT")
    assert released == ["CLOSE_QUICK_EXIT", "SHORT"]


def test_two_closes_only_once_prefer_quick(coalesce):
    released = []
    coalesce.set_dispatch(lambda p, fp: released.append(p["action"]))
    coalesce.submit(*_msg("CLOSE_RSI_EXIT", price=3290))
    coalesce.submit(*_msg("CLOSE_QUICK_EXIT", price=3288))
    coalesce.flush_now("ETHUSDT")
    assert released == ["CLOSE_QUICK_EXIT"]


def test_two_opens_only_latest(coalesce):
    released = []
    coalesce.set_dispatch(lambda p, fp: released.append((p["action"], p["price"])))
    coalesce.submit(*_msg("LONG", price=3300))
    time.sleep(0.02)
    coalesce.submit(*_msg("SHORT", price=3310))
    coalesce.flush_now("ETHUSDT")
    assert released == [("SHORT", 3310)]


def test_three_messages_close_once_then_open(coalesce):
    released = []
    coalesce.set_dispatch(lambda p, fp: released.append(p["action"]))
    coalesce.submit(*_msg("CLOSE_QUICK_EXIT", price=3290))
    coalesce.submit(*_msg("CLOSE_RSI_EXIT", price=3288))
    coalesce.submit(*_msg("SHORT", price=3301))
    coalesce.flush_now("ETHUSDT")
    assert released == ["CLOSE_QUICK_EXIT", "SHORT"]


def test_in_window_same_fingerprint_dropped(coalesce):
    released = []
    coalesce.set_dispatch(lambda p, fp: released.append(p["action"]))
    m = _msg("LONG", price=3300)
    assert coalesce.submit(*m) == "buffered"
    assert coalesce.submit(*m) == "coalesced_drop"
    coalesce.flush_now("ETHUSDT")
    assert released == ["LONG"]


def test_timer_callback_flushes(coalesce, monkeypatch):
    """超时兜底：timer 回调清空缓存并派发（不依赖真实 sleep）。"""
    monkeypatch.setattr(
        "app.services.webhook_symbol_coalesce.get_settings",
        lambda: MagicMock(WEBHOOK_COALESCE_SEC=1.5),
    )
    c = reset_coalesce_for_tests()
    released = []
    c.set_dispatch(lambda p, fp: released.append(p["action"]))
    assert c.submit(*_msg("SHORT", price=3300)) == "buffered"
    assert c.pending_depth() == 1
    c._on_timer("ETHUSDT")
    assert released == ["SHORT"]
    assert c.pending_depth() == 0


def test_idempotency_60s_includes_price():
    assert IDEMPOTENCY_TTL_SEC == 60
    a = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3300.5})
    b = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3399.0})
    assert a != b  # price part of key
    c = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3300.5})
    assert a == c
    d = compute_fingerprint({"action": "SHORT", "symbol": "ETHUSDT", "price": 3300.5})
    assert a != d


def test_webhook_server_uses_coalesce_not_seq_gate():
    import inspect
    import app.webhook_server as ws

    src = inspect.getsource(ws.webhook)
    assert "get_coalesce" in src
    assert "get_seq_gate" not in src
