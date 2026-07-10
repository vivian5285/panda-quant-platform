"""Manual TV-aligned positions: adopt TP123 + SL, never flatten unless opposite."""

from unittest.mock import MagicMock

import pytest

from app.core.startup_reconcile import (
    StartupReconcileMixin,
    finalize_recovery_tv_params,
    live_matches_tv_direction,
    prepare_manual_adopt,
)


def test_live_matches_tv_direction_uses_entry_tv():
    assert live_matches_tv_direction(
        {"latest_entry_tv_action": "LONG", "latest_tv_action": "CLOSE"},
        "LONG",
    )


def test_finalize_recovery_derives_missing_tp3():
    class Sup:
        tv_tps = [2050.0, 2100.0, 0.0]
        tv_sl = 0.0
        last_tv_side = "LONG"
        watched_entry = 2000.0
        tv_price = 2000.0
        current_atr = 30.0
        regime = 3

    sup = Sup()
    report: dict = {"open_log_entry": 2000.0}
    recovery = {
        "latest_tv": {"action": "CLOSE", "tv_tps": [2050.0, 2100.0, 0.0]},
        "latest_entry_tv": {
            "action": "LONG",
            "tv_tps": [2050.0, 2100.0, 0.0],
            "atr": 30.0,
            "regime": 3,
            "price": 2000.0,
            "tv_sl": 1900.0,
        },
    }
    finalize_recovery_tv_params(sup, report, recovery)
    assert sup.tv_tps[2] > 0
    assert sup.tv_sl == pytest.approx(1900.0)
    assert "tv_tps_derived_from_regime" in report.get("warnings", [])


def test_prepare_manual_adopt_resets_consumed():
    class Sup:
        watched_qty = 0.42
        initial_qty = 1.0
        base_qty = 0.0
        consumed_tp_levels = [1]

    sup = Sup()
    prepare_manual_adopt(sup)
    assert sup.initial_qty == 0.42
    assert sup.consumed_tp_levels == []
    assert sup.adopted_manual is True


class _WatchHost(StartupReconcileMixin):
    def __init__(self):
        self.user_id = 1
        self.monitoring = False
        self.watched_qty = 0.0
        self.current_side = None
        self.watched_entry = 0.0
        self.last_tv_side = "LONG"
        self._close_all = MagicMock()
        self._log = MagicMock()
        self._alert = MagicMock()


def test_idle_watch_does_not_flatten_manual_on_tv_close():
    host = _WatchHost()
    host._get_active_position = MagicMock(
        return_value={"size": 0.42, "side": "LONG", "entry_price": 3600.0},
    )
    host._is_dust_qty = MagicMock(return_value=False)
    host._should_finalize_tp_victory = MagicMock(return_value=False)
    host._reconcile_radar_context = MagicMock(
        return_value={"latest_tv_action": "CLOSE", "latest_entry_tv_action": "LONG"},
    )
    host._load_idle_recovery_context = MagicMock(
        return_value={
            "latest_tv": {"action": "CLOSE"},
            "latest_entry_tv": {"action": "LONG", "tv_tps": [3700, 3800, 3900], "tv_sl": 3500},
            "trade": None,
            "open_log": None,
        },
    )
    host.recover_on_startup = MagicMock(
        return_value={"has_position": True, "monitoring": True, "startup_summary": "TP3/3"},
    )

    host._run_idle_live_watch()

    host._close_all.assert_not_called()
    host.recover_on_startup.assert_called_once()
