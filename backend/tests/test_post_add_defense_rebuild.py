"""Post-add defense rebuild — TP123 qty/price realign + radar refresh."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor


def _make_supervisor(**kwargs):
    client = MagicMock()
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 1000.0,
        "available_balance": 500.0,
    }
    client.get_current_price.return_value = 2000.0
    client.get_open_orders.return_value = []
    client.place_market_order.return_value = {}
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 15

    sup = PositionSupervisor(user_id=1, client=client, initial_principal=1000.0, **kwargs)
    sup.regime = 3
    sup.current_side = "LONG"
    sup.tv_tps = [2100.0, 2200.0, 2300.0]
    sup.tv_sl = 1950.0
    sup.current_atr = 12.5
    sup.base_qty = 1.0
    sup.consumed_tp_levels = []
    sup.on_trade_open = MagicMock(return_value=1)
    return sup, client


def test_rebuild_defenses_after_tv_add_nuclear_and_radar():
    sup, client = _make_supervisor()
    sup._cancel_all_tp_limit_orders = MagicMock(return_value=1)
    sup._nuclear_realign_tp = MagicMock(
        return_value={"matched_full": 3, "expected": 3, "pending_prices": [2100, 2200, 2300]}
    )
    sup._sync_tv_hard_stop = MagicMock(return_value={"aligned": True, "stop_price": 1950.0})
    sup._refresh_radar_state_on_recover = MagicMock()
    sup._radar_sl_to_pass = MagicMock(return_value=1980.0)
    sup._ensure_radar_sl = MagicMock(return_value=True)
    sup._audit_tp_levels = MagicMock(
        return_value={"matched_full": 3, "expected": 3, "levels": [], "issues": [], "pending_prices": []}
    )
    sup._expected_tp_levels = MagicMock(
        return_value=[
            {"level": 1, "qty": 0.27, "price": 2100.0},
            {"level": 2, "qty": 0.48, "price": 2200.0},
            {"level": 3, "qty": 0.75, "price": 2300.0},
        ]
    )
    sup._format_audit_summary = MagicMock(return_value="ok")

    with patch("app.core.binance_smart_defense.time.sleep"):
        result = sup._rebuild_defenses_after_tv_add(
            1.5,
            2010.0,
            entry_type="PROFIT_ADD",
            prev_tv_tps=[2050.0, 2150.0, 2250.0],
        )

    sup._cancel_all_tp_limit_orders.assert_called_once()
    sup._nuclear_realign_tp.assert_called_once()
    sup._sync_tv_hard_stop.assert_called_once_with(1.5, force_replace=True)
    sup._refresh_radar_state_on_recover.assert_called_once()
    sup._ensure_radar_sl.assert_called_once()
    assert result["live_qty"] == 1.5
    assert sup.initial_qty == 1.5
    assert result["prev_tv_tps"] == [2050.0, 2150.0, 2250.0]
    assert len(result["tp_slices"]) == 3
    assert result["aligned"] is True


def test_add_to_position_redirects_to_flatten_open():
    """妈妈版：加仓禁用，_add_to_position → 先平后开。"""
    sup, client = _make_supervisor()
    flat = MagicMock(return_value=True)
    open_pos = MagicMock(return_value={"status": "ok"})
    rebuild = MagicMock()
    with patch.object(sup, "_force_flat_before_open", flat), \
         patch.object(sup, "_open_position", open_pos), \
         patch.object(sup, "_rebuild_defenses_after_tv_add", rebuild):
        result = PositionSupervisor._add_to_position(sup, "LONG", 2000.0, "PYRAMID")
    flat.assert_called_once()
    open_pos.assert_called_once_with("LONG", 2000.0)
    rebuild.assert_not_called()
    assert result.get("status") == "ok"


def test_rebuild_keeps_initial_qty_when_tp_consumed():
    sup, _ = _make_supervisor()
    sup.consumed_tp_levels = [1]
    sup.initial_qty = 1.0
    sup._cancel_all_tp_limit_orders = MagicMock(return_value=0)
    sup._nuclear_realign_tp = MagicMock(return_value={"matched_full": 2, "expected": 2})
    sup._sync_tv_hard_stop = MagicMock(return_value={})
    sup._refresh_radar_state_on_recover = MagicMock()
    sup._audit_tp_levels = MagicMock(
        return_value={"matched_full": 2, "expected": 2, "levels": [], "issues": []}
    )
    sup._expected_tp_levels = MagicMock(return_value=[])
    sup._format_audit_summary = MagicMock(return_value="")

    with patch("app.core.binance_smart_defense.time.sleep"):
        sup._rebuild_defenses_after_tv_add(1.4, 2005.0, entry_type="PROFIT_ADD")

    assert sup.initial_qty == pytest.approx(1.4)
