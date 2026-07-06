"""Adverse radar guard: staged stop-loss on wrong-way price drift."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.adverse_radar_guard import (
    ADVERSE_ARM_PCT,
    ADVERSE_SL_TIERS,
    AdverseRadarMixin,
    adverse_move_pct,
    compute_adverse_stop_plan,
)
from app.core.position_supervisor import PositionSupervisor


def test_adverse_move_pct_long_underwater():
    assert adverse_move_pct(2000.0, 1960.0, "LONG") == pytest.approx(0.02, rel=0.01)


def test_adverse_move_pct_short_underwater():
    assert adverse_move_pct(2000.0, 2040.0, "SHORT") == pytest.approx(0.02, rel=0.01)


def test_adverse_move_pct_favorable_is_zero():
    assert adverse_move_pct(2000.0, 2050.0, "LONG") == 0.0


def test_compute_adverse_stop_plan_long():
    plan = compute_adverse_stop_plan(2000.0, "LONG", 0.9, round_qty_fn=lambda x: round(x, 3))
    assert len(plan) == 3
    assert plan[0]["stop_price"] == pytest.approx(1960.0, rel=0.001)
    assert plan[1]["stop_price"] == pytest.approx(1940.0, rel=0.001)
    assert plan[2]["stop_price"] == pytest.approx(1900.0, rel=0.001)
    assert sum(p["qty"] for p in plan) == pytest.approx(0.9, rel=0.01)


class _AdverseProbe(AdverseRadarMixin):
    exchange_id = "binance"
    user_id = 1
    current_side = "SHORT"
    watched_entry = 2000.0
    adverse_sl_armed = False
    adverse_sl_prices = []
    symbol = "ETHUSDT"

    def __init__(self):
        self.client = MagicMock()
        self.client.get_open_orders.return_value = []
        self.client.place_stop_market_order.return_value = {"orderId": 1}
        self.on_log = MagicMock()
        self.on_alert = MagicMock()

    def _close_order_side(self):
        return "BUY"

    def _get_active_position(self):
        return {"size": 0.6, "entry_price": 2000.0, "side": "SHORT"}

    def _log(self, *a, **k):
        pass

    def _alert(self, *a, **k):
        pass

    def _save_state(self):
        pass


def test_arm_adverse_staged_stops_places_three_tiers():
    probe = _AdverseProbe()
    with patch.object(probe, "_verify_adverse_stops", return_value=3):
        result = probe._arm_adverse_staged_stops(0.6, 0.025)
    assert result["armed"] is True
    assert probe.adverse_sl_armed is True
    assert len(probe.adverse_sl_prices) == 3
    assert probe.client.place_stop_market_order.call_count == 3


def test_process_adverse_guard_waits_until_2pct():
    probe = _AdverseProbe()
    assert probe._process_adverse_radar_guard(0.6, 1980.0, 0.01) is False
    assert probe.adverse_sl_armed is False


def test_process_adverse_guard_arms_at_2pct():
    probe = _AdverseProbe()
    with patch.object(probe, "_arm_adverse_staged_stops", return_value={"armed": True}) as arm:
        assert probe._process_adverse_radar_guard(0.6, 1960.0, 0.02) is True
    arm.assert_called_once()


def test_binance_supervisor_has_adverse_radar():
    sup = PositionSupervisor(user_id=1, client=MagicMock())
    assert hasattr(sup, "_process_adverse_radar_guard")
    assert ADVERSE_ARM_PCT == 0.02
    assert ADVERSE_SL_TIERS == (0.02, 0.03, 0.05)
