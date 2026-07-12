"""Flat position → immediate TP123 teardown."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor
from app.core.startup_reconcile import StartupReconcileMixin


class _PurgeHost(StartupReconcileMixin):
    def __init__(self):
        self.user_id = 1
        self.symbol = "ETHUSDT"
        self.current_side = "LONG"
        self.watched_qty = 0.043
        self.tv_tps = [1810.0, 1820.0, 1830.0]
        self.client = MagicMock()
        self._alert = MagicMock()
        self._log = MagicMock()

    def _cancel_all_tp_limit_orders(self, *, flat_purge=False):
        assert flat_purge is True
        return 3

    def _cancel_tp_orders_for_consumed_levels(self):
        return 0

    def _cancel_binance_all_close_stops(self):
        return 1


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.get_open_orders.return_value = [
        {
            "orderId": 101,
            "type": "LIMIT",
            "side": "SELL",
            "reduceOnly": True,
            "price": "1810.0",
            "origQty": "0.011",
        },
        {
            "orderId": 102,
            "type": "LIMIT",
            "side": "SELL",
            "reduceOnly": True,
            "price": "1820.0",
            "origQty": "0.015",
        },
        {
            "orderId": 103,
            "type": "LIMIT",
            "side": "SELL",
            "reduceOnly": True,
            "price": "1830.0",
            "origQty": "0.017",
        },
    ]
    client.cancel_order.return_value = True
    sup = PositionSupervisor(user_id=6, client=client)
    sup.watched_qty = 0.043
    sup.current_side = "LONG"
    sup.tv_tps = [1810.0, 1820.0, 1830.0]
    return sup


def test_purge_defense_orders_on_flat_cancels_tp123(supervisor):
    supervisor._alert = MagicMock()
    detail = supervisor._purge_defense_orders_on_flat("manual_flat", notify=True)
    assert detail["cancelled_tp"] == 3
    assert supervisor.client.cancel_order.call_count == 3
    supervisor._alert.assert_called_once()
    args = supervisor._alert.call_args[0]
    assert args[1] == "MANUAL_FLAT_TP_PURGE"


def test_flat_orphan_tp_matches_reduce_only_without_side(supervisor):
    supervisor.current_side = None
    supervisor._flat_purge_side = "LONG"
    order = {
        "type": "LIMIT",
        "side": "SELL",
        "reduceOnly": True,
        "price": "1810.0",
    }
    assert supervisor._is_flat_orphan_tp_order(order) is True


def test_handle_manual_flat_detected_purges_then_books(supervisor):
    with patch.object(supervisor, "_purge_defense_orders_on_flat", return_value={"cancelled_tp": 3}) as mock_purge, patch.object(
        supervisor, "_handle_detected_flat", return_value=True
    ) as mock_flat:
        supervisor._handle_manual_flat_detected("空仓巡检：账本有仓但实盘已平")
    mock_purge.assert_called_once_with("manual_flat", notify=True)
    mock_flat.assert_called_once_with("manual_flat", skip_eager_purge=True)


def test_startup_reconcile_mixin_purge_host():
    host = _PurgeHost()
    detail = host._purge_defense_orders_on_flat("idle_patrol", notify=True)
    assert detail["cancelled_tp"] == 3
    host.client.cancel_all_open_orders.assert_called_once_with("ETHUSDT")
    host._alert.assert_called_once()
