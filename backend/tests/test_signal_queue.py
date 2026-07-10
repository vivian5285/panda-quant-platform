"""Per-user signal queue and empty CLOSE_PROTECT handling."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor, SIGNAL_QUEUE_TTL


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.get_current_price.return_value = 3600.0
    client.cancel_all_open_orders.return_value = None
    client.get_funding_fees.return_value = 0.0
    sup = PositionSupervisor(user_id=7, client=client)
    sup.on_log = MagicMock()
    sup.on_alert = MagicMock()
    sup.on_trade_close = MagicMock()
    return sup


def test_close_protect_empty_logs_and_alerts(supervisor):
    supervisor.current_trade_id = None

    with patch.object(
        supervisor.position_manager,
        "get_position",
        return_value={"positionAmt": "0"},
    ):
        supervisor._close_all(
            "🛡️ 保护性全平：动能衰竭",
            tv_side="LONG",
            tv_pnl_pct=-1.23,
            close_action="CLOSE_PROTECT",
        )

    log_types = [c.args[1] for c in supervisor.on_log.call_args_list]
    assert "CLOSE_PROTECT_EMPTY" in log_types
    alert_types = [c.args[2] for c in supervisor.on_alert.call_args_list]
    assert "CLOSE_PROTECT_EMPTY" in alert_types
    supervisor.on_trade_close.assert_not_called()


def test_close_with_position_still_logs_close(supervisor):
    supervisor.current_trade_id = 99
    supervisor.current_side = "LONG"
    supervisor.watched_entry = 3500.0
    supervisor.watched_qty = 1.0

    with patch.object(
        supervisor.position_manager,
        "get_position",
        side_effect=[
            {"positionAmt": "1.0", "entryPrice": "3500"},
            {"positionAmt": "1.0", "entryPrice": "3500"},
            {"positionAmt": "0"},
        ],
    ):
        supervisor._close_all(
            "🛡️ 保护性全平：动能衰竭",
            tv_side="LONG",
            tv_pnl_pct=-1.0,
            close_action="CLOSE_PROTECT",
        )

    log_types = [c.args[1] for c in supervisor.on_log.call_args_list]
    assert "CLOSE" in log_types
    assert "CLOSE_PROTECT_EMPTY" not in log_types
    supervisor.on_trade_close.assert_called_once()


def test_handle_signal_waits_for_lock_instead_of_dropping(supervisor):
    supervisor._lock.acquire()
    supervisor.client.get_position.return_value = {"positionAmt": "0"}
    results: list[dict] = []

    def run_signal():
        results.append(
            supervisor.handle_signal({
                "action": "CLOSE_PROTECT",
                "regime": 2,
                "reason": "test",
                "side": "LONG",
            })
        )

    worker = threading.Thread(target=run_signal)
    worker.start()
    time.sleep(0.3)
    supervisor._lock.release()
    worker.join(timeout=SIGNAL_QUEUE_TTL + 5)

    assert worker.is_alive() is False
    assert results
    assert results[0]["status"] == "ok"
    assert results[0]["action"] == "CLOSE_PROTECT"
