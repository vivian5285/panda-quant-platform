"""Integration tests for TV risk-formula OPEN/ADD entry routing."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor


def _make_supervisor(**kwargs):
    client = MagicMock()
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 1000.0,
        "available_balance": 500.0,
    }
    client.get_current_price.return_value = 1892.43
    client.place_market_order.return_value = {}
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 25

    sup = PositionSupervisor(user_id=1, client=client, initial_principal=1000.0, **kwargs)
    sup.regime = 3
    sup.tv_price = 1892.43
    sup.tv_sl = 1892.43 - 14.02
    sup.tv_tps = [2100.0, 2200.0, 2300.0]
    sup.on_trade_open = MagicMock(return_value=1)
    sup._protect_and_monitor = MagicMock()
    sup._sync_tv_hard_stop = MagicMock(return_value={"aligned": True, "stop_price": 1878.41})
    sup._enforce_regime_cap_alignment = MagicMock(return_value={})
    return sup, client


def test_open_uses_tv_risk_formula():
    sup, client = _make_supervisor()
    sup._apply_tv_entry_context({
        "entry_type": "OPEN",
        "regime": 3,
        "risk_pct": 2.03,
        "leverage": 25,
        "qty_ratio": 1.0,
    })
    qty, meta = sup._resolve_entry_qty(1892.43)
    assert meta["sizing_mode"] == "tv_risk_formula"
    assert qty == pytest.approx(1.45, abs=0.01)
    assert meta.get("risk_pct") == pytest.approx(2.03)


def test_open_missing_risk_pct_refuses():
    sup, _ = _make_supervisor()
    sup._apply_tv_entry_context({"entry_type": "OPEN", "regime": 3, "leverage": 25})
    qty, meta = sup._resolve_entry_qty(1892.43)
    assert qty == 0
    assert meta.get("error") == "missing_risk_pct"


def test_pyramid_uses_tv_formula_times_ratio():
    sup, client = _make_supervisor()
    sup.base_qty = 1.45
    sup._apply_tv_entry_context({
        "entry_type": "PYRAMID",
        "qty_ratio": 0.5,
        "regime": 3,
        "risk_pct": 2.03,
        "leverage": 25,
    })
    qty, meta = sup._resolve_entry_qty(1892.43)
    assert meta["sizing_mode"] == "tv_risk_formula"
    assert qty == pytest.approx(0.72, abs=0.02)


def test_tv_leverage_preferred():
    sup, _ = _make_supervisor()
    sup.leverage = 25
    sup._apply_tv_entry_context({
        "entry_type": "OPEN",
        "risk_pct": 2.03,
        "leverage": 10,
        "qty_ratio": 1.0,
    })
    assert sup._resolve_entry_leverage() == 10


def test_pyramid_same_side_does_not_require_force_flat_path():
    """Same-side ADD resolves qty via TV formula (no OPEN flat-then-open)."""
    sup, _ = _make_supervisor()
    sup.base_qty = 1.45
    sup.current_side = "LONG"
    sup.last_tv_side = "LONG"
    sup._apply_tv_entry_context({
        "entry_type": "PYRAMID",
        "qty_ratio": 0.5,
        "regime": 3,
        "risk_pct": 2.03,
        "leverage": 25,
    })
    qty, meta = sup._resolve_entry_qty(1892.43)
    assert qty == pytest.approx(0.72, abs=0.02)
    assert meta["sizing_mode"] == "tv_risk_formula"
    assert meta["entry_type"] == "PYRAMID"
