"""Idle live exchange watch — adopt positions while VPS book is flat."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.startup_reconcile import StartupReconcileMixin
from app.services.trading_alerts import should_push_trading_dingtalk


class _WatchHost(StartupReconcileMixin):
    def __init__(self):
        self.user_id = 1
        self.monitoring = False
        self.watched_qty = 0.0
        self.initial_qty = 0.0
        self.current_side = None
        self.watched_entry = 0.0
        self.last_tv_side = "LONG"
        self.client = MagicMock()
        self.symbol = "ETHUSDT"
        self.on_alert = MagicMock()


def test_idle_book_is_flat():
    host = _WatchHost()
    assert host._idle_book_is_flat() is True
    host.watched_qty = 0.5
    assert host._idle_book_is_flat() is False


def test_idle_watch_adopts_same_direction_position():
    host = _WatchHost()
    host._get_active_position = MagicMock(
        return_value={"size": 0.42, "side": "LONG", "entry_price": 3600.0},
    )
    host._is_dust_qty = MagicMock(return_value=False)
    host._should_finalize_tp_victory = MagicMock(return_value=False)
    host._reconcile_radar_context = MagicMock(
        return_value={"latest_tv_action": "LONG"},
    )
    host._load_idle_recovery_context = MagicMock(
        return_value={"latest_tv": {"action": "LONG"}, "trade": None, "open_log": None},
    )
    host._log = MagicMock()
    host._alert = MagicMock()
    host.recover_on_startup = MagicMock(
        return_value={
            "has_position": True,
            "monitoring": True,
            "startup_summary": "浮亏/防护轨 | TP3/3",
        },
    )

    host._run_idle_live_watch()

    host.recover_on_startup.assert_called_once()
    host._alert.assert_called_once()
    assert host._alert.call_args[0][1] == "IDLE_WATCH"


def test_idle_watch_force_aligns_opposite():
    host = _WatchHost()
    host.last_tv_side = "LONG"
    host._get_active_position = MagicMock(
        return_value={"size": 0.42, "side": "SHORT", "entry_price": 3600.0},
    )
    host._is_dust_qty = MagicMock(return_value=False)
    host._should_finalize_tp_victory = MagicMock(return_value=False)
    host._reconcile_radar_context = MagicMock(
        return_value={"latest_tv_action": "LONG"},
    )
    host._load_idle_recovery_context = MagicMock(return_value={})
    host._try_force_align_opposite_to_tv = MagicMock(return_value={"force_aligned": True})
    host.recover_on_startup = MagicMock()

    host._run_idle_live_watch()

    host._try_force_align_opposite_to_tv.assert_called_once()
    host.recover_on_startup.assert_not_called()


def test_idle_watch_reconciles_stale_book_flat():
    host = _WatchHost()
    host.watched_qty = 0.5
    host.current_side = "LONG"
    host._get_active_position = MagicMock(return_value=None)
    host._idle_reconcile_stale_book_flat = MagicMock(return_value=True)
    host._alert = MagicMock()

    host._run_idle_live_watch()

    host._idle_reconcile_stale_book_flat.assert_called_once()
    host._alert.assert_called_once()


def test_idle_watch_dingtalk_push():
    assert should_push_trading_dingtalk("IDLE_WATCH", "info") is True
