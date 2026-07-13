"""Tests for unified startup reconciliation."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.binance_smart_defense import BinanceSmartDefenseMixin
from app.core.startup_reconcile import (
    StartupReconcileMixin,
    classify_startup_pnl_track,
    format_startup_defense_summary,
)


def test_classify_loss_shield_when_underwater():
    assert classify_startup_pnl_track(2000.0, 1900.0, "LONG", radar_progress=0.2) == "loss_shield"


def test_classify_profit_radar_when_progress_full():
    assert classify_startup_pnl_track(2000.0, 2010.0, "LONG", radar_progress=1.0) == "profit_radar"


def test_classify_loss_shield_when_profit_but_radar_not_active():
    assert classify_startup_pnl_track(2000.0, 2010.0, "LONG", radar_progress=0.66) == "loss_shield"


def test_format_startup_summary():
    s = format_startup_defense_summary({
        "pnl_track": "loss_shield",
        "adverse_pct": 5.0,
        "tp_matched": 3,
        "tp_expected": 3,
        "shield": {"aligned": True},
        "defenses_skipped": True,
    })
    assert "浮亏/防护轨" in s
    assert "TP3/3" in s
    assert "未重复挂单" in s


class _StartupProbe(StartupReconcileMixin, AdverseRadarMixin, BinanceSmartDefenseMixin):
    user_id = 1
    exchange_id = "binance"
    symbol = "ETHUSDT"
    current_side = "LONG"
    watched_entry = 2000.0
    watched_qty = 0.6
    regime = 3
    regime_settings = {
        3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
    }
    tv_tps = [2050.0, 2100.0, 2150.0]
    tv_sl = 1900.0
    current_atr = 30.0
    current_sl = 2000.0
    best_price = 2000.0
    adverse_sl_armed = False
    adverse_sl_prices = []
    adverse_consumed_tiers = []
    adverse_arm_dingtalk_sent = False

    def __init__(self):
        self.client = MagicMock()
        self.client.get_open_orders.return_value = []
        self.client.place_stop_market_order.return_value = {"orderId": 1}
        self.client.place_limit_order.return_value = {"orderId": 2}

    def _close_order_side(self):
        return "SELL"

    def _get_active_position(self):
        return {"size": 0.6, "entry_price": 2000.0, "side": "LONG"}

    def _resolve_live_qty(self, q):
        return 0.6

    def _radar_activation_progress(self, curr_px):
        return 0.0 if curr_px < 2040 else 1.0

    def _is_radar_active(self):
        return False

    def _refresh_radar_state_on_recover(self, *a, **k):
        pass

    def _save_state(self):
        pass

    def _log(self, *a, **k):
        pass

    def _def_log(self, *a, **k):
        pass

    def _alert(self, *a, **k):
        pass


def test_unified_startup_loss_track_arms_shield():
    probe = _StartupProbe()
    plan = probe._compute_adverse_stop_plan(0.6)
    stop_order = {
        "type": "STOP_MARKET",
        "orderId": 1,
        "stopPrice": str(plan[0]["stop_price"]),
        "closePosition": True,
        "side": "SELL",
    }
    placed = {"done": False}

    def _open_orders(_symbol):
        return [stop_order] if placed["done"] else []

    def _place_stop(*_args, **_kwargs):
        placed["done"] = True
        return {"orderId": 1}

    probe.client.get_open_orders.side_effect = _open_orders
    probe.client.place_stop_limit_order.side_effect = _place_stop
    with patch.object(probe, "_startup_wait_live_book", lambda: None), patch(
        "app.core.adverse_radar_guard.time.sleep", lambda *_: None,
    ), patch("app.core.binance_smart_defense.time.sleep", lambda *_: None):
        result = probe._unified_startup_defense_reconcile(0.6, 2000.0, 1900.0)
    assert result["pnl_track"] == "loss_shield"
    assert result["tp_expected"] == 3
    probe.client.place_stop_limit_order.assert_called()


def test_unified_startup_profit_track_coexist_shield():
    probe = _StartupProbe()
    probe.adverse_sl_armed = True
    with patch.object(probe, "_startup_wait_live_book", lambda: None), patch.object(
        probe, "_sync_binance_merged_stop", return_value={"aligned": True, "merged": True},
    ) as merged, patch.object(probe, "_handoff_shield_to_radar", return_value=True):
        result = probe._unified_startup_defense_reconcile(0.6, 2000.0, 2050.0)
    assert result["pnl_track"] == "profit_radar"
    assert merged.called
