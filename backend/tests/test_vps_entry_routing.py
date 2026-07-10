"""Integration tests for VPS OPEN/ADD entry routing."""

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
    client.place_market_order.return_value = {}
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 15

    sup = PositionSupervisor(user_id=1, client=client, initial_principal=1000.0, **kwargs)
    sup.regime = 1
    sup.tv_price = 2000.0
    sup.tv_sl = 1955.0
    sup.tv_tps = [2100.0, 2200.0, 2300.0]
    sup.on_trade_open = MagicMock(return_value=1)
    sup._protect_and_monitor = MagicMock()
    sup._sync_tv_hard_stop = MagicMock(return_value={"aligned": True, "stop_price": 1955.0})
    sup._enforce_regime_cap_alignment = MagicMock(return_value={})
    return sup, client


def test_open_uses_vps_formula_not_margin_pct():
    sup, client = _make_supervisor()
    sup._apply_tv_entry_context({"entry_type": "OPEN", "regime": 1})
    qty, meta = sup._resolve_entry_qty(2000.0)
    assert meta["sizing_mode"] == "vps_open"
    assert qty == pytest.approx(0.619, rel=0.02)
    assert "margin_pct" not in meta


def test_pyramid_uses_base_qty_times_ratio():
    sup, client = _make_supervisor()
    sup.base_qty = 0.619
    sup._apply_tv_entry_context({
        "entry_type": "PYRAMID",
        "qty_ratio": 0.5,
        "regime": 1,
    })
    qty, meta = sup._resolve_entry_qty(2000.0)
    assert meta["sizing_mode"] == "vps_add"
    assert qty == pytest.approx(0.310, rel=0.02)


def test_pyramid_adds_without_cancel_all():
    sup, client = _make_supervisor()
    sup.base_qty = 0.619
    sup.add_count = 0
    sup._apply_tv_entry_context({
        "entry_type": "PYRAMID",
        "qty_ratio": 0.99,
        "regime": 1,
    })
    sup._smart_realign_defenses = MagicMock(return_value={"matched": 3, "expected": 3})
    with patch.object(sup.position_manager, "get_position") as gp:
        gp.side_effect = [
            {"positionAmt": "0.619", "entryPrice": "2000"},
            {"positionAmt": "0.929", "entryPrice": "2005"},
        ]
        result = sup._add_to_position("LONG", 2000.0, "PYRAMID")
    client.cancel_all_open_orders.assert_not_called()
    assert result["status"] == "ok"
    assert sup.base_qty == pytest.approx(0.619)
    assert sup.add_count == 1


def test_pyramid_skipped_when_max_add_times_reached():
    sup, client = _make_supervisor()
    sup.base_qty = 0.619
    sup.add_count = 2
    sup._apply_tv_entry_context({"entry_type": "PYRAMID", "regime": 1})
    result = sup._handle_tv_entry(
        "LONG", 2000.0, has_pos=True, current_side="LONG",
    )
    assert result["status"] == "skipped"
    client.place_market_order.assert_not_called()
