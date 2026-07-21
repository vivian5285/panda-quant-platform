"""Integration tests for RISK20 OPEN entry routing."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_supervisor import PositionSupervisor
from app.core.tv_entry_sizing import SIZING_MODE


def _make_supervisor(**kwargs):
    client = MagicMock()
    client.get_futures_account_summary.return_value = {
        "total_margin_balance": 1000.0,
        "available_balance": 500.0,
    }
    client.get_current_price.return_value = 3300.0
    client.place_market_order.return_value = {}
    client.trading_symbol = "ETHUSDT"
    client.exchange_id = "binance"
    client.trading_leverage = 5

    sup = PositionSupervisor(user_id=1, client=client, initial_principal=1000.0, **kwargs)
    sup.regime = 3
    sup.tv_price = 3300.0
    sup.tv_sl = 3200.0
    sup.tv_tps = [3400.0, 3500.0, 3600.0]
    sup._tv_entry_fields = {"tv_qty": 1.0, "sizing_mode": SIZING_MODE}
    sup.on_trade_open = MagicMock(return_value=1)
    sup._protect_and_monitor = MagicMock()
    sup._sync_tv_hard_stop = MagicMock(return_value={"aligned": True, "stop_price": 3200.0})
    sup._enforce_regime_cap_alignment = MagicMock(return_value={})
    return sup, client


def test_open_uses_risk20_formula():
    sup, client = _make_supervisor()
    qty, meta = sup._resolve_entry_qty(3300.0)
    assert meta["sizing_mode"] == SIZING_MODE
    assert qty == pytest.approx(1.0, abs=1e-9)


def test_open_missing_tv_qty_refuses():
    sup, _ = _make_supervisor()
    sup._tv_entry_fields = {}
    qty, meta = sup._resolve_entry_qty(3300.0)
    assert qty == 0
    assert meta.get("error") == "missing_tv_qty"


def test_pyramid_entry_type_disabled():
    from app.core.tv_entry_sizing import resolve_vps_entry_qty_eth

    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000,
        initial_principal=1000,
        entry_type="PYRAMID",
        base_qty=1,
        price=3300,
        tv_sl=3200,
        exchange_leverage=5,
        round_fn=lambda x: x,
        symbol="ETHUSDT",
        tv_qty=1.0,
    )
    assert qty == 0
    assert meta.get("error") == "add_disabled"


def test_tv_leverage_bound_to_5():
    sup, client = _make_supervisor()
    client.trading_leverage = 25
    client.set_leverage = MagicMock(return_value={})
    sup.leverage = 25
    assert sup._resolve_entry_leverage() == 5
    assert sup._bind_tv_leverage() == 5
    assert sup.leverage == 5
    assert client.trading_leverage == 5
    qty, meta = sup._resolve_entry_qty(3300.0)
    assert meta["leverage"] == 5
    assert meta["sizing_mode"] == SIZING_MODE
    assert qty > 0


def test_force_flat_before_open_still_sizes():
    """先平后开后仍用 RISK20 算仓（需 stop + tv_qty）。"""
    sup, _ = _make_supervisor()
    tv_sl = 3200.0
    sup.tv_sl = tv_sl
    sup._tv_hard_sl_price = tv_sl
    sup.position_manager = MagicMock()
    sup.position_manager.get_position.return_value = None
    sup._get_active_position = MagicMock(return_value=None)
    sup._count_open_book_orders = MagicMock(return_value=0)
    sup._purge_defense_orders_on_flat = MagicMock()
    sup._cancel_all_verified = MagicMock()
    sup._disarm_adverse_staged_stops = MagicMock()
    sup._save_state = MagicMock()
    with patch.object(sup, "_reset_adverse_radar", return_value=None):
        ok = PositionSupervisor._force_flat_before_open(sup, "TV OPEN [LONG] 铁律·先平后开")
    assert ok is True
    # Re-arm sizing inputs after flat (RISK20 needs stop + tv_qty)
    sup.tv_sl = tv_sl
    sup._tv_entry_fields = {"tv_qty": 1.0, "sizing_mode": SIZING_MODE}
    qty, meta = sup._resolve_entry_qty(3300.0)
    assert qty == pytest.approx(1.0, abs=1e-9)
    assert meta.get("error") is None


def test_open_position_recovers_wiped_tv_sl():
    """If tv_sl was wiped before sizing, recover from _pending_open_tv_sl."""
    sup, client = _make_supervisor()
    tv_sl = 3200.0
    sup.tv_sl = 0.0
    sup._tv_hard_sl_price = 0.0
    sup._pending_open_tv_sl = tv_sl
    sup._cancel_binance_all_close_stops = MagicMock(return_value=0)
    result = PositionSupervisor._open_position(sup, "LONG", 3300.0)
    assert float(sup.tv_sl) == pytest.approx(tv_sl)
    assert result.get("status") != "error" or result.get("reason") != "missing_tv_sl"
    client.place_market_order.assert_called()
