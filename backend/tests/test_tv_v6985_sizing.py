"""v6.9.85 TV proportional sizing and entry_type routing."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.tv_entry_sizing import (
    compute_tv_eth_qty,
    compute_tv_notional_usd,
    normalize_risk_pct,
    parse_tv_entry_fields,
    resolve_entry_order_qty_eth,
)
from app.core.position_supervisor import PositionSupervisor
from app.services.webhook_guard import validate_signal_payload


def test_normalize_risk_pct_percent_points():
    assert normalize_risk_pct(1.35) == pytest.approx(0.0135)
    assert normalize_risk_pct(0.5) == pytest.approx(0.005)


def test_compute_tv_notional_usd_formula():
    margin, notional, cap = compute_tv_notional_usd(
        10000.0, risk_pct=1.35, leverage=3, qty_ratio=1.0,
    )
    assert margin == pytest.approx(135.0)
    assert notional == pytest.approx(405.0)
    assert cap == pytest.approx(30000.0)


def test_compute_tv_notional_pyramid_half_ratio():
    _, notional, _ = compute_tv_notional_usd(
        10000.0, risk_pct=1.35, leverage=3, qty_ratio=0.5,
    )
    assert notional == pytest.approx(202.5)


def test_compute_tv_eth_qty():
    qty, meta = compute_tv_eth_qty(
        live_balance=10000.0,
        initial_principal=10000.0,
        risk_pct=1.35,
        leverage=3,
        qty_ratio=1.0,
        price=2000.0,
        round_fn=lambda x: round(x, 3),
    )
    assert qty == pytest.approx(0.203)
    assert meta["sizing_mode"] == "tv_v6985_proportional"
    assert meta["risk_pct"] == pytest.approx(1.35)


def test_parse_tv_entry_fields_defaults():
    fields = parse_tv_entry_fields({"action": "LONG"})
    assert fields["entry_type"] == "OPEN"
    assert fields["qty_ratio"] == 1.0
    assert fields["uses_tv_sizing"] is False


def test_parse_tv_entry_fields_v6985():
    fields = parse_tv_entry_fields({
        "action": "LONG",
        "entry_type": "PYRAMID",
        "risk_pct": 1.35,
        "leverage": 3,
        "qty_ratio": 0.5,
    })
    assert fields["entry_type"] == "PYRAMID"
    assert fields["uses_tv_sizing"] is True
    assert fields["tv_leverage"] == 3.0


def test_resolve_entry_order_qty_falls_back_without_risk_pct():
    qty, meta = resolve_entry_order_qty_eth(
        live_balance=1000.0,
        initial_principal=700.0,
        price=2000.0,
        regime_margin_pct=0.35,
        exchange_leverage=10,
        round_fn=lambda x: round(x, 3),
        tv_fields={"uses_tv_sizing": False},
    )
    assert qty > 0
    assert "sizing_mode" not in meta or meta.get("sizing_mode") != "tv_v6985_proportional"


def test_webhook_guard_accepts_v6985_fields():
    ok, err = validate_signal_payload({
        "action": "LONG",
        "secret": "x",
        "entry_type": "PYRAMID",
        "risk_pct": 1.35,
        "leverage": 3,
        "qty_ratio": 0.5,
        "price": 2000,
        "tv_sl": 1900,
        "tv_tp1": 2100,
        "tv_tp2": 2200,
        "tv_tp3": 2300,
    })
    assert ok, err


def test_webhook_guard_rejects_bad_entry_type():
    ok, err = validate_signal_payload({
        "action": "LONG",
        "secret": "x",
        "price": 2000,
        "entry_type": "INVALID",
    })
    assert not ok
    assert "entry_type" in err


def _make_supervisor(**kwargs):
    client = MagicMock()
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 10000.0,
        "available_balance": 5000.0,
    }
    client.get_current_price.return_value = 2000.0
    client.place_market_order.return_value = {}
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 5

    sup = PositionSupervisor(user_id=1, client=client, initial_principal=10000.0, **kwargs)
    sup.regime = 3
    sup.tv_price = 2000.0
    sup.tv_tps = [2100.0, 2200.0, 2300.0]
    sup.tv_sl = 1900.0
    sup.on_trade_open = MagicMock(return_value=1)
    sup._protect_and_monitor = MagicMock()
    sup._sync_tv_hard_stop = MagicMock(return_value={"aligned": True, "stop_price": 1900.0})
    return sup, client


def test_open_entry_type_forces_flat_before_open():
    sup, client = _make_supervisor()
    sup._apply_tv_entry_context({
        "entry_type": "OPEN",
        "risk_pct": 1.35,
        "leverage": 3,
        "qty_ratio": 1.0,
    })
    with patch.object(sup.position_manager, "get_position") as gp:
        gp.side_effect = [
            {"positionAmt": "0.5", "entryPrice": "1990"},
            {"positionAmt": "0", "entryPrice": "0"},
            {"positionAmt": "0.202", "entryPrice": "2000"},
        ]
        sup._close_all = MagicMock()
        sup._wait_until_flat = MagicMock(return_value=True)
        result = sup._handle_tv_entry("LONG", 2000.0, has_pos=True, current_side="LONG")
    sup._close_all.assert_called_once()
    assert result["status"] == "ok"
    client.set_leverage.assert_called_with(sup.symbol, leverage=5)


def test_pyramid_adds_without_cancel_all():
    sup, client = _make_supervisor()
    sup._apply_tv_entry_context({
        "entry_type": "PYRAMID",
        "risk_pct": 1.35,
        "leverage": 3,
        "qty_ratio": 0.5,
    })
    sup._sync_tv_hard_stop = MagicMock(return_value={"aligned": True, "stop_price": 1900.0})
    sup._smart_realign_defenses = MagicMock(return_value={"matched": 3, "expected": 3})
    with patch.object(sup.position_manager, "get_position") as gp:
        gp.side_effect = [
            {"positionAmt": "0.202", "entryPrice": "2000"},
            {"positionAmt": "0.303", "entryPrice": "2005"},
        ]
        result = sup._add_to_position("LONG", 2000.0, "PYRAMID")
    client.cancel_all_open_orders.assert_not_called()
    assert result["status"] == "ok"
    assert result["detail"]["entry_type"] == "PYRAMID"
    sup._sync_tv_hard_stop.assert_called_once()
