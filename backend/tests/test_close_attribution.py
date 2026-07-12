"""Close attribution and flat-detection hardening."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.core.close_attribution import diagnose_flat_close, format_close_reason
from app.core.position_supervisor import PositionSupervisor


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.get_current_price.return_value = 1780.43
    client.get_funding_fees.return_value = -0.0166
    client.get_account_trades.return_value = [
        {
            "side": "SELL",
            "price": "1780.43",
            "qty": "0.2",
            "maker": False,
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
            "realizedPnl": "0.022",
        }
    ]
    sup = PositionSupervisor(user_id=6, client=client)
    sup.watched_qty = 0.2
    sup.watched_entry = 1780.32
    sup.current_side = "LONG"
    sup.current_trade_id = 99
    sup.trade_opened_at = datetime.now(timezone.utc).timestamp() - 3600
    sup.tv_tps = [1790.0, 1800.0, 1810.0]
    sup.regime = 3
    return sup


def test_diagnose_consumed_tp1_does_not_fake_tp_on_stop_exit():
    """Remaining leg closed below entry must not be labeled TP[1] from consumed_tp_levels."""
    attr = diagnose_flat_close(
        client=MagicMock(get_account_trades=MagicMock(return_value=[
            {
                "side": "SELL",
                "price": "1779.33",
                "qty": "0.046",
                "maker": False,
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
                "realizedPnl": "-0.31",
            },
        ])),
        symbol="ETHUSDT",
        side="LONG",
        qty=0.046,
        entry=1786.17,
        trade_opened_at=datetime.now(timezone.utc).timestamp() - 3600,
        consumed_tp_levels=[1],
        tv_tps=[1810.0, 1830.0, 1850.0],
        trigger="sentinel_zero",
        had_position_before_close=False,
        recent_tv_close=None,
        radar_active=True,
        current_sl=1796.43,
    )
    assert attr["close_origin"] == "exchange_stop"
    assert "TP[1]" not in attr["human_reason"]
    assert "TP1" not in attr["human_reason"]
    assert attr["evidence"]["tp_price_matches"] == []


def test_diagnose_tp_only_when_fill_price_matches():
    attr = diagnose_flat_close(
        client=MagicMock(get_account_trades=MagicMock(return_value=[
            {
                "side": "SELL",
                "price": "1830.00",
                "qty": "0.020",
                "maker": True,
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
                "realizedPnl": "0.88",
            },
        ])),
        symbol="ETHUSDT",
        side="LONG",
        qty=0.020,
        entry=1786.17,
        trade_opened_at=None,
        consumed_tp_levels=[1],
        tv_tps=[1810.0, 1830.0, 1850.0],
        trigger="sentinel_zero",
        had_position_before_close=False,
        radar_active=True,
        current_sl=1796.43,
    )
    assert attr["close_origin"] == "exchange_limit_tp"
    assert "TP[2]" in attr["human_reason"] or "TP2" in str(attr["evidence"]["tp_price_matches"])


def test_diagnose_near_entry_without_radar_is_manual_exchange():
    attr = diagnose_flat_close(
        client=MagicMock(get_account_trades=MagicMock(return_value=[
            {"side": "SELL", "price": "1780.43", "qty": "0.2", "maker": False, "time": 1},
        ])),
        symbol="ETHUSDT",
        side="LONG",
        qty=0.2,
        entry=1780.32,
        trade_opened_at=None,
        consumed_tp_levels=[],
        tv_tps=[1790, 1800, 1810],
        trigger="sentinel_zero",
        had_position_before_close=False,
        recent_tv_close=None,
        radar_active=False,
    )
    assert attr["close_origin"] == "manual_exchange"
    assert attr["close_actor"] == "human"
    assert "开仓价" in attr["human_reason"]


def test_diagnose_recent_tv_close_attributes_tv():
    recent = {
        "action": "CLOSE",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    attr = diagnose_flat_close(
        client=MagicMock(get_account_trades=MagicMock(return_value=[])),
        symbol="ETHUSDT",
        side="LONG",
        qty=0.2,
        entry=1780.32,
        trade_opened_at=None,
        consumed_tp_levels=[],
        tv_tps=[],
        trigger="sentinel_zero",
        had_position_before_close=False,
        recent_tv_close=recent,
        radar_active=False,
    )
    assert attr["close_origin"] == "tv_forced"
    assert attr["close_actor"] == "tv_signal"


def test_format_close_reason_includes_origin_label():
    attr = {
        "human_reason": "盘口已平：疑为人工",
        "origin_label": "交易所端人工操作",
    }
    text = format_close_reason(attr)
    assert "人工" in text
    assert "交易所端人工操作" in text


def test_confirm_exchange_flat_requires_consecutive_zeros(supervisor):
    pm = supervisor.position_manager
    with patch.object(pm, "get_position", side_effect=[
        {"positionAmt": 0},
        {"positionAmt": 0.2},
        {"positionAmt": 0},
        {"positionAmt": 0},
        {"positionAmt": 0},
    ]), patch("app.core.position_supervisor.FLAT_CONFIRM_POLLS", 3), patch(
        "app.core.position_supervisor.FLAT_CONFIRM_DELAY", 0
    ):
        assert supervisor._confirm_exchange_flat() is False

    with patch.object(pm, "get_position", side_effect=[
        {"positionAmt": 0},
        {"positionAmt": 0},
        {"positionAmt": 0},
    ]), patch("app.core.position_supervisor.FLAT_CONFIRM_POLLS", 3), patch(
        "app.core.position_supervisor.FLAT_CONFIRM_DELAY", 0
    ):
        assert supervisor._confirm_exchange_flat() is True


def test_handle_detected_flat_rejects_transient_zero(supervisor):
    with patch.object(supervisor, "_purge_defense_orders_on_flat", return_value={"cancelled_tp": 2}) as mock_purge, patch.object(
        supervisor, "_confirm_exchange_flat", return_value=False
    ), patch.object(supervisor, "_close_all") as mock_close:
        ok = supervisor._handle_detected_flat("sentinel_zero")
    assert ok is False
    mock_purge.assert_called_once()
    mock_close.assert_not_called()


def test_handle_detected_flat_eager_purges_before_confirm(supervisor):
    with patch.object(supervisor, "_purge_defense_orders_on_flat", return_value={"cancelled_tp": 3}) as mock_purge, patch.object(
        supervisor, "_confirm_exchange_flat", return_value=True
    ), patch.object(supervisor, "_close_all") as mock_close, patch.object(
        supervisor, "_diagnose_flat_close", return_value={"human_reason": "人工平仓"}
    ):
        supervisor._handle_detected_flat("sentinel_zero")
    mock_purge.assert_called_once_with("sentinel_zero", notify=False)
    mock_close.assert_called_once()


def test_handle_detected_flat_books_close_with_attribution(supervisor):
    with patch.object(supervisor.position_manager, "get_position", side_effect=[
        {"positionAmt": 0},
        {"positionAmt": 0},
    ]), patch.object(supervisor, "_confirm_exchange_flat", return_value=True), patch.object(
        supervisor, "_diagnose_flat_close", return_value={
            "close_trigger": "sentinel_zero",
            "close_origin": "manual_exchange",
            "close_actor": "human",
            "human_reason": "疑为人工平仓",
            "anomaly": False,
        }
    ), patch.object(supervisor, "_close_all") as mock_close:
        ok = supervisor._handle_detected_flat("sentinel_zero")
    assert ok is True
    mock_close.assert_called_once()
    _args, kwargs = mock_close.call_args
    assert kwargs.get("close_trigger") == "sentinel_zero"
    assert kwargs.get("attribution") is not None
