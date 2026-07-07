"""Startup radar SL must exist on exchange, not only in memory."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor
from app.core.startup_reconcile import classify_startup_pnl_track


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
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
