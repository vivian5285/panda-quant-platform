"""Startup recover + breakeven helpers for PositionSupervisor."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor, MIN_SL_MOVE


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.get_current_price.return_value = 3600.0
    client.cancel_all_open_orders.return_value = None
    sup = PositionSupervisor(user_id=42, client=client)
    return sup


def test_breakeven_sl_active_long(supervisor):
    supervisor.current_side = "LONG"
    supervisor.watched_entry = 3500.0
    supervisor.current_sl = 3500.0
    assert not supervisor._breakeven_sl_active()
    supervisor.current_sl = 3505.0
    assert supervisor._breakeven_sl_active()


def test_breakeven_sl_active_short(supervisor):
    supervisor.current_side = "SHORT"
    supervisor.watched_entry = 3500.0
    supervisor.current_sl = 3500.0
    assert not supervisor._breakeven_sl_active()
    supervisor.current_sl = 3495.0
    assert supervisor._breakeven_sl_active()


def test_recover_restores_radar_and_rebuilds_defenses(supervisor):
    supervisor._save_state()
    supervisor.best_price = 3650.0
    supervisor.current_sl = 3620.0
    supervisor.watched_entry = 3500.0
    supervisor.current_side = "LONG"
    supervisor.last_tv_side = "LONG"
    supervisor.tv_tps = [3600.0, 3700.0, 3800.0]
    supervisor.regime = 2
    supervisor._save_state()

    supervisor.client.get_current_price.return_value = 3660.0

    with patch.object(
        supervisor.position_manager,
        "get_position",
        return_value={"positionAmt": "1.5", "entryPrice": "3500.0"},
    ), patch.object(supervisor, "_ensure_defenses") as ensure:
        ensure.return_value = {"skipped": True, "aligned": True}
        audit = supervisor.recover_on_startup(
            open_trade_id=99,
            recovery_context={
                "trade": {"id": 99, "side": "LONG", "regime": 2, "tv_tps": [3600, 3700, 3800]},
                "open_log": {"side": "LONG", "entry": 3500, "qty": 1.5, "tv_tps": [3600, 3700, 3800]},
                "latest_tv": {"action": "LONG", "tv_tps": [3600, 3700, 3800]},
                "checks": [],
            },
        )

    assert audit["has_position"] is True
    assert audit["defenses_skipped"] is True
    assert audit["breakeven_active"] is True
    assert audit["best_price"] == 3660.0
    assert audit["current_sl"] == 3620.0
    ensure.assert_called_once()
    call_kw = ensure.call_args[1]
    assert call_kw.get("force_rebuild") is False
    supervisor.client.cancel_all_open_orders.assert_not_called()


def test_recover_falls_back_to_db_trade_context(supervisor):
    supervisor.client.get_current_price.return_value = 3580.0

    with patch.object(
        supervisor.position_manager,
        "get_position",
        return_value={"positionAmt": "-0.8", "entryPrice": "3600.0"},
    ), patch.object(supervisor, "_ensure_defenses") as ensure:
        ensure.return_value = {"skipped": True, "aligned": True}
        audit = supervisor.recover_on_startup(
            open_trade_id=7,
            recovery_context={
                "trade": {"id": 7, "side": "SHORT", "regime": 4, "tv_tps": [3500, 3400, 3300]},
                "latest_tv": {"action": "SHORT", "tv_tps": [3500, 3400, 3300], "regime": 4},
                "checks": [],
            },
        )

    assert audit["tv_tps"] == [3500.0, 3400.0, 3300.0]
    assert supervisor.regime == 4
    assert supervisor.last_tv_side == "SHORT"
    assert audit["defenses_skipped"] is True


def test_min_sl_move_matches_tick():
    assert MIN_SL_MOVE == 0.01
