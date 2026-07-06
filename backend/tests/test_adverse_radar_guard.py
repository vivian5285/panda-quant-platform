"""Adverse radar guard + smart defense orchestration tests."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.adverse_radar_guard import (
    ADVERSE_ARM_PCT,
    ADVERSE_SL_TIERS,
    AdverseRadarMixin,
    adverse_move_pct,
    compute_adverse_stop_plan,
    is_floating_profit,
    match_adverse_tier_fill,
)
from app.core.position_supervisor import PositionSupervisor


def test_adverse_move_pct_long_underwater():
    assert adverse_move_pct(2000.0, 1960.0, "LONG") == pytest.approx(0.02, rel=0.01)


def test_is_floating_profit_long():
    assert is_floating_profit(2000.0, 2010.0, "LONG") is True
    assert is_floating_profit(2000.0, 1990.0, "LONG") is False


def test_compute_adverse_stop_plan_skips_consumed_tiers():
    plan = compute_adverse_stop_plan(
        2000.0, "LONG", 0.6,
        round_qty_fn=lambda x: round(x, 3),
        consumed_tiers={0.02, 0.03},
    )
    assert len(plan) == 1
    assert plan[0]["tier_pct"] == 0.05
    assert plan[0]["qty"] == pytest.approx(0.6, rel=0.01)


def test_match_adverse_tier_fill_detects_2pct_slice():
    tier = match_adverse_tier_fill(
        2000.0, "LONG", 0.9, 0.297,
        round_qty_fn=lambda x: round(x, 3),
    )
    assert tier == pytest.approx(0.02, rel=0.01)


class _AdverseProbe(AdverseRadarMixin):
    exchange_id = "binance"
    user_id = 1
    current_side = "LONG"
    watched_entry = 2000.0
    adverse_sl_armed = False
    adverse_sl_prices = []
    adverse_consumed_tiers = []
    symbol = "ETHUSDT"
    regime = 3
    regime_settings = {
        3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
    }
    tv_tps = [2050.0, 2100.0, 2150.0]
    current_atr = 30.0
    current_sl = 2000.0
    best_price = 2000.0
    consumed_tp_levels = []

    def __init__(self):
        self.client = MagicMock()
        self.client.get_open_orders.return_value = []
        self.client.place_stop_market_order.return_value = {"orderId": 1}
        self.on_log = MagicMock()
        self.on_alert = MagicMock()

    def _close_order_side(self):
        return "SELL"

    def _get_active_position(self):
        return {"size": 0.6, "entry_price": 2000.0, "side": "LONG"}

    def _classify_qty_change(self, old_qty, new_qty):
        return "tp1_filled"

    def _radar_sl_to_pass(self):
        return 2003.0

    def _is_radar_active(self):
        return self.current_sl > self.watched_entry

    def _radar_activation_progress(self, curr_px):
        return 1.0 if curr_px >= 2040 else 0.0

    def _process_radar_trailing(self, *a, **k):
        return True

    def _smart_realign_defenses(self, *a, **k):
        return {"matched": 3, "expected": 3, "audit": {}}

    def _realign_radar_defenses(self, *a, **k):
        return True

    def _log(self, *a, **k):
        pass

    def _alert(self, *a, **k):
        pass

    def _save_state(self):
        pass


def test_disarm_only_on_floating_profit():
    probe = _AdverseProbe()
    probe.adverse_sl_armed = True
    assert probe._should_disarm_adverse_for_recovery(1990.0) is False
    assert probe._should_disarm_adverse_for_recovery(2010.0) is True


def test_orchestrate_qty_change_tp_fill_boosts_radar():
    probe = _AdverseProbe()
    with patch.object(probe, "_boost_radar_after_tp_fill") as boost:
        orch = probe._orchestrate_qty_change(0.9, 0.603, 2000.0, 2055.0)
    assert orch["change_type"] == "tp1_filled"
    boost.assert_called_once()


def test_orchestrate_qty_change_adverse_hit_repairs_remaining():
    probe = _AdverseProbe()
    probe.adverse_sl_armed = True

    def classify(old, new):
        return "adverse_sl_2pct"

    with patch.object(probe, "_classify_reduction_cause", side_effect=classify), patch.object(
        probe, "_repair_adverse_stops_remaining", return_value={"armed": True},
    ) as repair:
        orch = probe._orchestrate_qty_change(0.9, 0.603, 2000.0, 1960.0)

    assert orch["change_type"] == "adverse_sl_2pct"
    assert 0.02 in probe._adverse_consumed_set()
    repair.assert_called_once()


def test_orchestrate_defense_monitoring_keeps_adverse_while_underwater():
    probe = _AdverseProbe()
    with patch.object(probe, "_process_adverse_radar_guard", return_value=True) as guard, patch.object(
        probe, "_process_radar_trailing",
    ) as trail:
        probe._orchestrate_defense_monitoring(0.6, 1960.0)
    guard.assert_called_once()
    trail.assert_not_called()


def test_orchestrate_defense_disarms_on_profit_recovery():
    probe = _AdverseProbe()
    probe.adverse_sl_armed = True
    probe.adverse_sl_prices = [1960.0]
    with patch.object(probe, "_disarm_adverse_staged_stops") as disarm, patch.object(
        probe, "_process_radar_trailing",
    ):
        probe._orchestrate_defense_monitoring(0.6, 2010.0)
    disarm.assert_called_once()


def test_binance_supervisor_has_orchestration():
    sup = PositionSupervisor(user_id=1, client=MagicMock())
    assert hasattr(sup, "_orchestrate_qty_change")
    assert hasattr(sup, "_orchestrate_defense_monitoring")
    assert ADVERSE_ARM_PCT == 0.02
    assert ADVERSE_SL_TIERS == (0.02, 0.03, 0.05)
