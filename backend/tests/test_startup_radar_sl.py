"""Startup radar SL must exist on exchange, not only in memory."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor
from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from app.core.startup_reconcile import classify_startup_pnl_track


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.configure_mock(exchange_id="binance", trading_symbol="ETHUSDT", trading_leverage=25)
    sup = PositionSupervisor(user_id=1, client=client)
    sup.current_side = "LONG"
    sup.watched_entry = 1786.17
    sup.current_sl = 1797.19
    sup.watched_qty = 0.046
    sup.initial_qty = 0.178
    sup.consumed_tp_levels = [1]
    sup.regime = 3
    sup.tv_tps = [1810.0, 1830.0, 1850.0]
    sup.current_atr = 25.0
    sup.best_price = 1820.0
    return sup


@pytest.fixture
def deepcoin_supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.configure_mock(
        exchange_id="deepcoin", trading_symbol="ETH-USDT-SWAP", trading_leverage=20,
    )
    with patch.object(DeepcoinPositionSupervisor, "_start_idle_flat_patrol"), patch.object(
        DeepcoinPositionSupervisor, "_start_signal_worker"
    ):
        sup = DeepcoinPositionSupervisor(user_id=2, client=client)
    sup.current_side = "LONG"
    sup.watched_entry = 1786.17
    sup.current_sl = 1797.19
    sup.watched_qty = 5
    sup.initial_qty = 12
    sup.consumed_tp_levels = [1]
    sup.regime = 3
    sup.tv_tps = [1810.0, 1830.0, 1850.0]
    sup.current_atr = 25.0
    sup.best_price = 1820.0
    return sup


def test_consumed_tp1_forces_profit_radar_track():
    track = classify_startup_pnl_track(
        1786.0, 1820.0, "LONG",
        radar_progress=0.0,
        radar_active=False,
        consumed_tp_levels=[1],
    )
    assert track == "profit_radar"


def test_finalize_startup_radar_sl_places_when_missing(supervisor):
    supervisor._has_stop_sl_near = MagicMock(side_effect=[False, False, True])
    supervisor._ensure_radar_sl = MagicMock(return_value=True)
    supervisor._realign_radar_defenses = MagicMock(return_value=True)
    supervisor._refresh_radar_state_on_recover = MagicMock()
    supervisor._alert = MagicMock()

    audit = supervisor._finalize_startup_radar_sl(
        0.046, 1786.17, 1820.0, "profit_radar",
    )

    assert audit["expected_sl"] > supervisor.watched_entry
    supervisor._ensure_radar_sl.assert_called()
    assert audit["live"] is True


def test_finalize_startup_skips_when_sl_already_on_book(supervisor):
    supervisor._has_stop_sl_near = MagicMock(return_value=True)
    supervisor._ensure_radar_sl = MagicMock()

    audit = supervisor._finalize_startup_radar_sl(
        0.046, 1786.17, 1820.0, "profit_radar",
    )

    assert audit["live"] is True
    supervisor._ensure_radar_sl.assert_not_called()


def test_deepcoin_finalize_startup_radar_sl_places_when_missing(deepcoin_supervisor):
    deepcoin_supervisor._has_stop_sl_near = MagicMock(side_effect=[False, False, True])
    deepcoin_supervisor._ensure_radar_sl = MagicMock(return_value=True)
    deepcoin_supervisor._realign_radar_defenses = MagicMock(return_value=True)

    audit = deepcoin_supervisor._finalize_startup_radar_sl(
        5, 1786.17, 1820.0, "profit_radar",
    )

    assert audit["expected_sl"] > deepcoin_supervisor.watched_entry
    deepcoin_supervisor._ensure_radar_sl.assert_called()
    assert audit["live"] is True


def test_startup_tp_reconcile_ok_without_radar_sl_on_book(supervisor):
    """TP2/2 aligned must not fail just because radar STOP is absent."""
    supervisor.consumed_tp_levels = [1]
    supervisor.watched_qty = 0.046
    supervisor.initial_qty = 0.178
    supervisor.client.get_current_price.return_value = 1820.0
    supervisor._audit_tp_levels = MagicMock(return_value={
        "expected": 2, "matched_full": 2, "orphans": [], "levels": [],
        "pending_prices": [1830.0, 1850.0], "issues": [],
    })
    supervisor._defenses_fully_ok = MagicMock(return_value=True)
    supervisor._ensure_radar_sl = MagicMock()

    result = supervisor._reconcile_tp_defenses_on_startup(
        0.046, 1786.17, dynamic_sl=None,
    )

    assert result.get("skipped") is True
    supervisor._ensure_radar_sl.assert_not_called()


def test_ensure_radar_sl_uses_close_position_and_verifies(supervisor):
    supervisor.current_side = "LONG"
    supervisor.symbol = "ETHUSDT"
    supervisor._sync_binance_merged_stop = MagicMock(
        return_value={"aligned": True, "armed": True, "merged": True},
    )

    ok = supervisor._ensure_radar_sl(1796.43, 0.046)

    assert ok is True
    supervisor._sync_binance_merged_stop.assert_called_once()
    args, kwargs = supervisor._sync_binance_merged_stop.call_args
    assert kwargs.get("radar_sl") == 1796.43
