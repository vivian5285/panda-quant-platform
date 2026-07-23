"""TV webhook symbol coalesce — 15s OPEN/CLOSE iron rule."""

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
        lambda: MagicMock(WEBHOOK_COALESCE_SEC=1.0),
    )
    c = reset_coalesce_for_tests()
    yield c
    c.flush_now()
    reset_coalesce_for_tests()


def _msg(action: str, symbol: str = "ETHUSDT", price: float = 3300.0, **extra):
    d = {"action": action, "symbol": symbol, "price": price, "token": "528586", **extra}
    return d, compute_fingerprint(d)


def test_coalesce_window_hard_capped_at_15s(monkeypatch):
    monkeypatch.setattr(
        "app.services.webhook_symbol_coalesce.get_settings",
        lambda: MagicMock(WEBHOOK_COALESCE_SEC=99.0),
    )
    c = WebhookSymbolCoalesce()
    assert c.window_sec() == 15.0


def test_coalesce_window_default_clamped(monkeypatch):
    monkeypatch.setattr(
        "app.services.webhook_symbol_coalesce.get_settings",
        lambda: MagicMock(WEBHOOK_COALESCE_SEC=1.0),
    )
    c = WebhookSymbolCoalesce()
    assert c.window_sec() == 1.0


def test_close_open_same_window_notifies_dingtalk(coalesce, monkeypatch):
    calls = []

    def fake_notify(severity, alert_type, title, message, detail=None):
        calls.append((severity, alert_type, title, message, detail))

    monkeypatch.setattr(
        "app.services.alert_service.notify_system",
        fake_notify,
    )
    released = []
    coalesce.set_dispatch(lambda p, fp: released.append(p["action"]))
    coalesce.submit(*_msg("CLOSE_QUICK_EXIT", price=3290))
    coalesce.submit(*_msg("SHORT", price=3301))
    coalesce.flush_now("ETHUSDT")
    assert released == ["CLOSE_QUICK_EXIT", "SHORT"]
    assert len(calls) == 1
    assert calls[0][1] == "COALESCE_WINDOW"
    assert "平仓+开仓同时到达" in calls[0][3]


def test_close_then_open_same_window_not_ignore_open(coalesce):
    """CLOSE first → still execute latest OPEN after close once."""
    released = []
    coalesce.set_dispatch(lambda p, fp: released.append(p["action"]))
    coalesce.submit(*_msg("CLOSE_QUICK_EXIT", price=3290))
    coalesce.submit(*_msg("SHORT", price=3301))
    coalesce.flush_now("ETHUSDT")
    assert released == ["CLOSE_QUICK_EXIT", "SHORT"]


def test_open_then_close_in_window_discards_close(coalesce):
    """OPEN first in window → CLOSE discarded; only OPEN executes."""
    released = []
    coalesce.set_dispatch(lambda p, fp: released.append(p["action"]))
    coalesce.submit(*_msg("SHORT", price=3301))
    coalesce.submit(*_msg("CLOSE_QUICK_EXIT", price=3290, reason="rev"))
    coalesce.flush_now("ETHUSDT")
    assert released == ["SHORT"]


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
    monkeypatch.setattr(
        "app.services.webhook_symbol_coalesce.get_settings",
        lambda: MagicMock(WEBHOOK_COALESCE_SEC=1.0),
    )
    c = reset_coalesce_for_tests()
    released = []
    c.set_dispatch(lambda p, fp: released.append(p["action"]))
    assert c.submit(*_msg("SHORT", price=3300)) == "buffered"
    assert c.pending_depth() == 1
    c._on_timer("ETHUSDT")
    assert released == ["SHORT"]
    assert c.pending_depth() == 0


def test_post_open_close_discarded_within_15s(monkeypatch):
    """Whitepaper: OPEN dispatched → CLOSE within 1–10s discarded."""
    monkeypatch.setattr(
        "app.services.webhook_symbol_coalesce.get_settings",
        lambda: MagicMock(WEBHOOK_COALESCE_SEC=1.0),
    )
    c = reset_coalesce_for_tests()
    released = []
    c.set_dispatch(lambda p, fp: released.append(p["action"]))
    c.submit(*_msg("LONG", price=3300))
    c.flush_now("ETHUSDT")
    assert released == ["LONG"]
    # Simulate CLOSE 5s after OPEN
    c._last_open_dispatched_at["ETHUSDT"] = time.time() - 5.0
    disp = c.submit(*_msg("CLOSE_QUICK_EXIT", price=3290))
    assert disp == "discarded_post_open"
    assert released == ["LONG"]


def test_post_open_close_accepted_after_15s(monkeypatch):
    """Whitepaper: CLOSE 20s after OPEN → independent close."""
    monkeypatch.setattr(
        "app.services.webhook_symbol_coalesce.get_settings",
        lambda: MagicMock(WEBHOOK_COALESCE_SEC=1.0),
    )
    c = reset_coalesce_for_tests()
    released = []
    c.set_dispatch(lambda p, fp: released.append(p["action"]))
    c.submit(*_msg("LONG", price=3300))
    c.flush_now("ETHUSDT")
    c._last_open_dispatched_at["ETHUSDT"] = time.time() - 20.0
    assert c.submit(*_msg("CLOSE_QUICK_EXIT", price=3290)) == "buffered"
    c.flush_now("ETHUSDT")
    assert released == ["LONG", "CLOSE_QUICK_EXIT"]


def test_idempotency_60s_includes_price():
    assert IDEMPOTENCY_TTL_SEC == 60
    a = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3300.5})
    b = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3399.0})
    assert a != b
    c = compute_fingerprint({"action": "LONG", "symbol": "ETHUSDT", "price": 3300.5})
    assert a == c
    d = compute_fingerprint({"action": "SHORT", "symbol": "ETHUSDT", "price": 3300.5})
    assert a != d


def test_coalesce_window_type_in_system_dingtalk():
    from app.services.alert_service import SYSTEM_DINGTALK_TYPES

    assert "COALESCE_WINDOW" in SYSTEM_DINGTALK_TYPES


def test_webhook_server_uses_coalesce_not_seq_gate():
    import inspect
    import app.webhook_server as ws

    src = inspect.getsource(ws.webhook)
    assert "get_coalesce" in src
    assert "get_seq_gate" not in src
