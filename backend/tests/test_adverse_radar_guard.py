"""Adverse radar guard — 10% hard stop at open + radar handoff tests."""

from unittest.mock import MagicMock, patch
import time

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


def test_compute_adverse_stop_plan_tv_sl_only():
    plan = compute_adverse_stop_plan(
        2000.0, "LONG", 0.6,
        round_qty_fn=lambda x: round(x, 3),
        tv_sl_price=1900.0,
    )
    assert len(plan) == 1
    assert plan[0]["source"] == "tv_hard_sl"
    assert plan[0]["stop_price"] == pytest.approx(1900.0, rel=0.001)
    assert plan[0]["qty"] == pytest.approx(0.6, rel=0.01)


def test_compute_adverse_stop_plan_empty_without_tv_sl():
    plan = compute_adverse_stop_plan(
        2000.0, "LONG", 0.6,
        round_qty_fn=lambda x: round(x, 3),
    )
    assert plan == []


def test_match_adverse_tier_fill_full_position():
    tier = match_adverse_tier_fill(
        2000.0, "LONG", 0.6, 0.6,
        round_qty_fn=lambda x: round(x, 3),
        tv_sl_price=1900.0,
    )
    assert tier == pytest.approx(-1.0, rel=0.01)


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
    tv_sl = 1900.0
    current_atr = 30.0
    current_sl = 2000.0
    best_price = 2000.0
    consumed_tp_levels = []

    def __init__(self):
        self.client = MagicMock()
        self.client.get_open_orders.return_value = []
        self.client.place_stop_market_order.return_value = {"orderId": 1}
        self.client.place_stop_limit_order.return_value = {"orderId": 1}
        self.client.place_limit_order.return_value = {"orderId": 2}
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

    def _current_tp_price(self):
        return 2045.0

    def _log(self, *a, **k):
        pass

    def _alert(self, *a, **k):
        pass

    def _save_state(self):
        pass


def test_latched_radar_never_revokes_on_path_collapse():
    """铁律：雷达锁定后路径回撤也不得解除。"""
    probe = _AdverseProbe()
    probe.radar_latched = True
    probe.current_sl = 2003.0
    probe.watched_entry = 2000.0
    probe.trade_opened_at = __import__("time").time() - 10.0
    probe.consumed_tp_levels = []
    probe._radar_activation_progress = lambda curr_px: 0.1  # collapsed path
    probe._alert = MagicMock()
    assert probe._radar_activation_reached(2001.0) is True
    assert probe.radar_latched is True
    assert float(probe.current_sl) == pytest.approx(2003.0)
    probe._alert.assert_not_called()
    # clear helper is no-op
    probe._clear_premature_radar_arm(2001.0, "should_ignore")
    assert probe.radar_latched is True
    assert float(probe.current_sl) == pytest.approx(2003.0)


def test_disarm_when_radar_activation_reached():
    probe = _AdverseProbe()
    probe.adverse_sl_armed = True
    assert probe._should_disarm_adverse_for_recovery(1990.0) is False
    assert probe._should_disarm_adverse_for_recovery(2045.0) is False


def test_disarm_shield_before_radar_is_noop_route_a():
    probe = _AdverseProbe()
    probe.adverse_sl_armed = True
    result = probe._disarm_shield_before_radar(2045.0)
    assert result.get("skipped") == "route_a_coexist"
    assert result.get("cancelled") == 0


def test_disarm_when_live_stop_even_if_flag_false():
    probe = _AdverseProbe()
    assert probe._should_disarm_adverse_for_recovery(2045.0) is False


def test_arm_at_open_places_close_position_stop():
    """Hard SL → closePosition 条件单（不与 TP123 reduceOnly 抢份额）。"""
    probe = _AdverseProbe()
    with patch("app.core.adverse_radar_guard.time.sleep", lambda *_: None):
        result = probe._arm_adverse_shield_at_open(0.6)
    assert result["armed"] is True
    assert result["placed"] == 1
    probe.client.place_stop_market_order.assert_called()
    args, kwargs = probe.client.place_stop_market_order.call_args
    assert args[0] == "SELL"
    assert float(args[1]) == pytest.approx(1900.0, rel=0.001)
    assert kwargs.get("quantity") is None
    probe.client.place_limit_order.assert_not_called()


def test_arm_aligned_with_close_position_stop():
    probe = _AdverseProbe()
    plan = probe._compute_adverse_stop_plan(0.6)
    probe.client.get_open_orders.return_value = [
        {
            "type": "STOP",
            "orderId": 1,
            "stopPrice": str(plan[0]["stop_price"]),
            "price": str(plan[0]["stop_price"] - 0.5),
            "origQty": str(plan[0]["qty"]),
            "side": "SELL",
        }
    ]
    result = probe._arm_adverse_shield_at_open(0.6)
    assert result.get("skipped") == "live_already_aligned"
    probe.client.place_stop_limit_order.assert_not_called()


def test_verify_retries_finds_delayed_stop():
    probe = _AdverseProbe()
    plan = probe._compute_adverse_stop_plan(0.6)
    stop_order = {
        "type": "STOP",
        "orderId": 1,
        "stopPrice": str(plan[0]["stop_price"]),
        "price": str(plan[0]["stop_price"] - 0.5),
        "origQty": str(plan[0]["qty"]),
        "side": "SELL",
    }
    responses = [[], [], [stop_order]]

    def _open_orders(_symbol):
        if responses:
            return responses.pop(0)
        return [stop_order]

    probe.client.get_open_orders.side_effect = _open_orders
    with patch("app.core.adverse_radar_guard.time.sleep", lambda *_: None):
        audit = probe._refresh_adverse_shield_audit(
            plan, retries=3, delay=0.01,
        )
    assert audit["aligned"] is True


def test_arm_aligned_with_algo_trigger_price_only():
    probe = _AdverseProbe()
    plan = probe._compute_adverse_stop_plan(0.6)
    probe.client.get_open_orders.return_value = [
        {
            "algoId": 9001,
            "orderId": 9001,
            "orderType": "STOP_MARKET",
            "type": "",
            "triggerPrice": str(plan[0]["stop_price"]),
            "closePosition": True,
            "side": "SELL",
            "isAlgoOrder": True,
        }
    ]
    result = probe._arm_adverse_shield_at_open(0.6)
    assert result.get("skipped") == "live_already_aligned"
    probe.client.place_stop_market_order.assert_not_called()


def test_collect_pending_algo_id_when_open_list_empty():
    probe = _AdverseProbe()
    plan = probe._compute_adverse_stop_plan(0.6)
    stop_px = plan[0]["stop_price"]
    probe.client.get_open_orders.return_value = []
    probe.client.get_algo_order.return_value = {
        "algoId": 9002,
        "orderId": 9002,
        "orderType": "STOP_MARKET",
        "type": "STOP_MARKET",
        "triggerPrice": str(stop_px),
        "closePosition": True,
        "side": "SELL",
        "isAlgoOrder": True,
    }
    probe._pending_adverse_algo_ids = [9002]
    audit = probe._audit_adverse_shield_live(plan)
    assert audit["aligned"] is True
    probe.client.get_algo_order.assert_called_with("ETHUSDT", 9002)


def test_disarm_clears_pending_algo_ids():
    probe = _AdverseProbe()
    probe.adverse_sl_armed = True
    probe._pending_adverse_algo_ids = [9002]
    with patch.object(probe, "_cancel_adverse_stop_orders", return_value=1) as cancel:
        probe._disarm_adverse_staged_stops(reason="radar_test", notify=False)
    cancel.assert_called_once()
    assert probe._pending_adverse_algo_ids == []


def test_disarm_flat_reset_does_not_alert_radar_handoff():
    probe = _AdverseProbe()
    probe.adverse_sl_armed = True
    probe.watched_qty = 0.0
    with patch.object(probe, "_cancel_adverse_stop_orders", return_value=1), patch.object(
        probe, "_alert",
    ) as alert:
        probe._disarm_adverse_staged_stops(reason="flat_reset", notify=True)
    alert.assert_not_called()


def test_sync_merged_stop_clamps_hot_radar_stop():
    probe = _AdverseProbe()
    probe.tv_sl = 1744.35
    probe.watched_entry = 1772.38
    probe.current_sl = 1791.0
    probe.client.get_open_orders.return_value = [
        {
            "type": "STOP_MARKET",
            "orderId": 1,
            "stopPrice": "1744.35",
            "closePosition": True,
            "side": "SELL",
        }
    ]
    with patch.object(probe, "_current_tp_price", return_value=1785.0), patch(
        "app.core.adverse_radar_guard.time.sleep", lambda *_: None,
    ):
        result = probe._sync_binance_merged_stop(0.6, radar_sl=1791.0)
    assert result.get("stop_price", 0) < 1785.0
    # Clamped stop uses closePosition (no reduceOnly qty fight with TP123)
    probe.client.place_stop_market_order.assert_called()
    kwargs = probe.client.place_stop_market_order.call_args.kwargs
    assert kwargs.get("quantity") is None
    probe.client.place_limit_order.assert_not_called()


def test_arm_skips_when_already_aligned():
    probe = _AdverseProbe()
    plan = probe._compute_adverse_stop_plan(0.6)
    probe.client.get_open_orders.return_value = [
        {
            "type": "STOP",
            "orderId": 1,
            "stopPrice": str(plan[0]["stop_price"]),
            "price": str(plan[0]["stop_price"] - 0.5),
            "origQty": str(plan[0]["qty"]),
            "side": "SELL",
        }
    ]
    result = probe._arm_adverse_shield_at_open(0.6)
    assert result.get("skipped") == "live_already_aligned"
    probe.client.place_stop_limit_order.assert_not_called()


def test_orchestrate_skips_hard_sl_when_radar_latched_on_rebound():
    """Latched radar must not fall back to adverse hard-stop repair on price rebound."""
    probe = _AdverseProbe()
    probe.current_side = "SHORT"
    probe.watched_entry = 1800.0
    probe.tv_sl = 1870.0
    probe.current_sl = 1798.2
    probe.best_price = 1770.0
    probe.radar_latched = True
    probe.tv_tps = [1780.0, 1770.0, 1760.0]
    rebound_px = 1790.0
    with patch.object(probe, "_process_adverse_radar_guard", return_value=True) as guard, patch.object(
        probe, "_process_radar_trailing", return_value=False,
    ) as trail, patch.object(
        probe, "_sync_binance_merged_stop", return_value={"aligned": True},
    ) as merged:
        probe._orchestrate_defense_monitoring(0.6, rebound_px)
    trail.assert_called_once()
    guard.assert_not_called()
    if merged.called:
        assert merged.call_args.kwargs.get("radar_sl") == pytest.approx(1798.2, rel=0.001)


def test_orchestrate_radar_coexist_route_a():
    probe = _AdverseProbe()
    probe.adverse_sl_armed = True
    probe.current_sl = 2003.0
    probe.radar_latched = True
    probe.trade_opened_at = time.time() - 300
    with patch.object(probe, "_process_adverse_radar_guard", return_value=True) as guard, patch.object(
        probe, "_process_radar_trailing", return_value=True,
    ) as trail, patch.object(
        probe, "_sync_binance_merged_stop", return_value={"aligned": True},
    ) as merged:
        probe._orchestrate_defense_monitoring(0.6, 2045.0)
    trail.assert_called_once()
    merged.assert_called_once()
    guard.assert_not_called()


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
    client = MagicMock()
    client.exchange_id = "binance"
    sup = PositionSupervisor(user_id=1, client=client)
    assert hasattr(sup, "_arm_adverse_shield_at_open")
    assert hasattr(sup, "_orchestrate_qty_change")
    assert ADVERSE_HARD_STOP_PCT == 0.10
    assert ADVERSE_REPAIR_COOLDOWN_SEC >= 15
