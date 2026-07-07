"""Adverse radar guard — 10% hard stop at open + radar handoff tests."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.adverse_radar_guard import (
    ADVERSE_HARD_STOP_PCT,
    ADVERSE_REPAIR_COOLDOWN_SEC,
    AdverseRadarMixin,
    adverse_hard_stop_price,
    adverse_move_pct,
    adverse_tier_stop_prices,
    compute_adverse_stop_plan,
    is_floating_profit,
    match_adverse_tier_fill,
)
from app.core.position_supervisor import PositionSupervisor


def test_adverse_hard_stop_price_long():
    assert adverse_hard_stop_price(2000.0, "LONG") == pytest.approx(1800.0, rel=0.001)


def test_adverse_hard_stop_price_short():
    assert adverse_hard_stop_price(2000.0, "SHORT") == pytest.approx(2200.0, rel=0.001)


def test_adverse_move_pct_long_underwater():
    assert adverse_move_pct(2000.0, 1800.0, "LONG") == pytest.approx(0.10, rel=0.01)


def test_compute_adverse_stop_plan_single_full_qty():
    plan = compute_adverse_stop_plan(
        2000.0, "LONG", 0.6,
        round_qty_fn=lambda x: round(x, 3),
    )
    assert len(plan) == 1
    assert plan[0]["tier_pct"] == ADVERSE_HARD_STOP_PCT
    assert plan[0]["stop_price"] == pytest.approx(1800.0, rel=0.001)
    assert plan[0]["qty"] == pytest.approx(0.6, rel=0.01)


def test_match_adverse_tier_fill_full_position():
    tier = match_adverse_tier_fill(
        2000.0, "LONG", 0.6, 0.6,
        round_qty_fn=lambda x: round(x, 3),
    )
    assert tier == pytest.approx(0.10, rel=0.01)


class _AdverseProbe(AdverseRadarMixin):
    exchange_id = "binance"
    user_id = 1
    current_side = "LONG"
    watched_entry = 2000.0
    adverse_sl_armed = False
    adverse_sl_prices = []
    adverse_consumed_tiers = []
    adverse_arm_dingtalk_sent = False
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
        self.client.place_stop_limit_order.return_value = {"orderId": 1}
        self.on_log = MagicMock()
        self.on_alert = MagicMock()

    def _close_order_side(self):
        return "SELL"

    def _get_active_position(self):
        return {"size": 0.6, "entry_price": 2000.0, "side": "LONG"}

    def _resolve_live_qty(self, fallback_qty):
        return 0.6

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


def test_disarm_when_radar_activation_reached():
    probe = _AdverseProbe()
    probe.adverse_sl_armed = True
    assert probe._should_disarm_adverse_for_recovery(1990.0) is False
    assert probe._should_disarm_adverse_for_recovery(2045.0) is True


def test_arm_at_open_places_single_stop_market():
    probe = _AdverseProbe()
    result = probe._arm_adverse_shield_at_open(0.6)
    assert result["armed"] is True
    assert result["placed"] == 1
    probe.client.place_stop_market_order.assert_called_once()


def test_arm_skips_when_already_aligned():
    probe = _AdverseProbe()
    plan = probe._compute_adverse_stop_plan(0.6)
    probe.client.get_open_orders.return_value = [
        {
            "type": "STOP_MARKET",
            "orderId": 1,
            "stopPrice": str(plan[0]["stop_price"]),
            "origQty": str(plan[0]["qty"]),
            "side": "SELL",
        }
    ]
    result = probe._arm_adverse_shield_at_open(0.6)
    assert result.get("skipped") == "live_already_aligned"
    probe.client.place_stop_market_order.assert_not_called()


def test_orchestrate_disarms_on_radar_activation():
    probe = _AdverseProbe()
    probe.adverse_sl_armed = True
    with patch.object(probe, "_disarm_adverse_staged_stops") as disarm, patch.object(
        probe, "_handoff_shield_to_radar", return_value=True,
    ):
        probe._orchestrate_defense_monitoring(0.6, 2045.0)
    disarm.assert_called_once()


def test_orchestrate_maintains_hard_stop_before_radar():
    probe = _AdverseProbe()
    with patch.object(probe, "_process_adverse_radar_guard", return_value=True) as guard, patch.object(
        probe, "_process_radar_trailing",
    ) as trail:
        probe._orchestrate_defense_monitoring(0.6, 1980.0)
    guard.assert_called_once()
    trail.assert_not_called()


def test_adverse_tier_prices_single_10pct():
    prices = adverse_tier_stop_prices(2000.0, "LONG")
    assert len(prices) == 1
    assert 1800.0 in prices


def test_binance_supervisor_has_orchestration():
    sup = PositionSupervisor(user_id=1, client=MagicMock())
    assert hasattr(sup, "_arm_adverse_shield_at_open")
    assert hasattr(sup, "_orchestrate_qty_change")
    assert ADVERSE_HARD_STOP_PCT == 0.10
    assert ADVERSE_REPAIR_COOLDOWN_SEC >= 15
