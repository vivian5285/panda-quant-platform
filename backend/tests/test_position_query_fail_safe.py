"""Position query failures must never be treated as flat."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.binance_client import BinanceClient
from app.core.exchange_errors import ExchangeTransientError, parse_binance_error
from app.core.position_supervisor import PositionSupervisor


def test_parse_binance_ban_until():
    meta = parse_binance_error(
        "APIError(code=-1003): Way too many requests; IP banned until 1784711514057."
    )
    assert meta["code"] == -1003
    assert meta["banned_until_ms"] == 1784711514057


def test_binance_get_position_raises_on_api_error():
    client = BinanceClient.__new__(BinanceClient)
    client.user_id = 6
    client.trading_symbol = "ETHUSDT"
    client._sym = lambda s=None: s or "ETHUSDT"
    client.client = MagicMock()
    client.client.futures_position_information.side_effect = RuntimeError(
        "APIError(code=-1003): banned until 1784711514057"
    )
    with pytest.raises(ExchangeTransientError) as ei:
        BinanceClient.get_position(client, "ETHUSDT")
    assert ei.value.is_ip_ban
    assert ei.value.banned_until_ms == 1784711514057


def test_recover_missed_flat_skips_when_query_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.exchange_id = "binance"
    client.trading_symbol = "ETHUSDT"
    client.trading_leverage = 5
    client.get_current_price.return_value = 1900.0
    sup = PositionSupervisor(user_id=6, client=client)
    sup.watched_qty = 0.033
    sup.current_side = "LONG"
    sup.initial_qty = 0.033
    alerts = []

    def _alert(*a, **k):
        alerts.append((a, k))

    sup._alert = _alert
    sup.position_manager.get_position = MagicMock(
        side_effect=ExchangeTransientError("banned", exchange="binance", code=-1003)
    )
    assert sup._recover_missed_flat_on_startup(was_monitoring=True) is False
    assert float(sup.watched_qty) == pytest.approx(0.033)
    assert sup.current_side == "LONG"
    assert getattr(sup, "_position_query_degraded", False) is True
    assert any("EXCHANGE_QUERY_FAIL" in str(x) for x in alerts)


def test_get_active_position_flat_only_on_confirmed_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock(exchange_id="binance", trading_symbol="ETHUSDT", trading_leverage=5)
    sup = PositionSupervisor(user_id=1, client=client)
    sup.position_manager.get_position = MagicMock(
        return_value={"positionAmt": "0", "entryPrice": "0"}
    )
    assert PositionSupervisor._get_active_position(sup) is None
    assert getattr(sup, "_position_query_degraded", False) is False
