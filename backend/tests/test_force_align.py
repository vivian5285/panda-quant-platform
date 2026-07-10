"""FORCE_ALIGN — opposite manual position vs TV direction."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor
from app.core.startup_reconcile import is_opposite_tv_live
from app.services.trading_alerts import format_force_align_detail_cn, should_push_trading_dingtalk


def test_is_opposite_tv_live():
    assert is_opposite_tv_live("LONG", "SHORT") is True
    assert is_opposite_tv_live("LONG", "LONG") is False
    assert is_opposite_tv_live(None, "LONG") is False


def test_force_align_dingtalk_detail():
    body = format_force_align_detail_cn(
        {
            "live_side": "SHORT",
            "tv_side": "LONG",
            "trigger": "sentinel",
            "qty": 0.42,
            "entry": 3620.0,
        },
        "binance",
    )
    assert "做多" in body
    assert "做空" in body
    assert "哨兵" in body


def test_sentinel_force_align_opposite():
    client = MagicMock()
    client.get_futures_account_summary.return_value = {"total_margin_balance": 1000.0}
    client.get_current_price.return_value = 2000.0
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 15

    sup = PositionSupervisor(user_id=1, client=client, initial_principal=1000.0)
    sup.monitoring = True
    sup.last_tv_side = "LONG"
    sup.watched_qty = 0.5
    sup.watched_entry = 2000.0
    sup.on_alert = MagicMock()

    with patch.object(sup, "_close_all") as close_all:
        assert sup._sentinel_force_align_if_opposite("SHORT") is True
    close_all.assert_called_once()
    assert should_push_trading_dingtalk("FORCE_ALIGN", "critical") is True
