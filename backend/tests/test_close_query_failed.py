"""QUERY_FAILED on close/flat must fail-closed refuse open."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.exchange_errors import ExchangeTransientError
from app.core.position_supervisor import PositionSupervisor


def _sup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.exchange_id = "binance"
    client.trading_symbol = "XAUUSDT"
    client.trading_leverage = 5
    client.get_current_price.return_value = 4100.0
    pm = MagicMock()
    s = PositionSupervisor(user_id=6, client=client)
    s.position_manager = pm
    s.canonical_symbol = "XAUUSDT"
    s.exchange_id = "binance"
    s._save_state = MagicMock()
    s._purge_defense_orders_on_flat = MagicMock()
    s._pause_trading = MagicMock()
    s._unbind_price_ws_listener = MagicMock()
    s._disarm_adverse_staged_stops = MagicMock()
    s._clear_position_local_state = MagicMock()
    s._reconcile_live_vs_book = MagicMock(return_value={"ok": True})
    return s, pm


def test_close_all_query_failed_returns_status(tmp_path, monkeypatch):
    s, pm = _sup(tmp_path, monkeypatch)
    pm.get_position.side_effect = ExchangeTransientError(
        "banned", code=-1003, banned_until_ms=1784810144199
    )
    out = s._close_all("tv open flatten")
    assert out["status"] == "QUERY_FAILED"
    assert s._last_close_all_status == "QUERY_FAILED"
    s.client.place_market_order.assert_not_called()


def test_force_flat_query_failed_aborts_open(tmp_path, monkeypatch):
    s, pm = _sup(tmp_path, monkeypatch)
    s._get_active_position = MagicMock(
        side_effect=ExchangeTransientError("banned", code=-1003, banned_until_ms=1)
    )
    ok = s._force_flat_before_open("TV OPEN SHORT")
    assert ok is False
    s._pause_trading.assert_called()
