"""Safe position float + dust scan must not crash on None / non-dict."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.exchange_errors import ExchangeTransientError
from app.core.position_supervisor import PositionSupervisor
from app.config import get_settings


def test_safe_pos_float_none():
    s = PositionSupervisor.__new__(PositionSupervisor)
    assert s._safe_pos_float(None) == 0.0
    assert s._safe_pos_float("") == 0.0
    assert s._safe_pos_float("1.5") == 1.5


def test_get_active_position_null_amt_not_float_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.exchange_id = "binance"
    client.trading_symbol = "ETHUSDT"
    client.trading_leverage = 5
    s = PositionSupervisor(user_id=6, client=client)
    s.position_manager = MagicMock()
    s.position_manager.get_position.return_value = {
        "positionAmt": None,
        "entryPrice": None,
    }
    assert s._get_active_position() is None


def test_dust_scan_query_failed_no_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.exchange_id = "binance"
    client.trading_symbol = "ETHUSDT"
    client.trading_leverage = 5
    s = PositionSupervisor(user_id=6, client=client)
    s._get_active_position = MagicMock(
        side_effect=ExchangeTransientError("banned", code=-1003)
    )
    assert s._scan_and_sweep_dust_on_startup() is False


def test_dust_scan_string_pos_no_index_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.exchange_id = "binance"
    client.trading_symbol = "ETHUSDT"
    client.trading_leverage = 5
    s = PositionSupervisor(user_id=6, client=client)
    s._get_active_position = MagicMock(return_value="not-a-dict")
    assert s._scan_and_sweep_dust_on_startup() is False


def test_idle_patrol_intervals_config():
    s = get_settings()
    assert float(s.IDLE_PATROL_INTERVAL_SEC) == 45.0
    assert float(s.IDLE_PATROL_FAIL_BACKOFF_SEC) == 120.0
