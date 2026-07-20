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


def test_force_flat_before_open_preserves_tv_sl():
    """Regression: pre-open clean must not wipe TV tv_sl (else missing_tv_sl on size)."""
    sup, _ = _make_supervisor()
    tv_sl = 1874.3871690506
    sup.tv_sl = tv_sl
    sup._tv_hard_sl_price = tv_sl
    sup._apply_tv_entry_context({
        "entry_type": "OPEN",
        "regime": 2,
        "risk_pct": 2.4,
        "leverage": 5,
        "qty_ratio": 1.0,
    })
    # Simulate empty book: force_flat only cleans orders/state
    sup.position_manager = MagicMock()
    sup.position_manager.get_position.return_value = None
    sup._get_active_position = MagicMock(return_value=None)
    sup._count_open_book_orders = MagicMock(return_value=0)
    sup._purge_defense_orders_on_flat = MagicMock()
    sup._cancel_all_verified = MagicMock()
    sup._disarm_adverse_staged_stops = MagicMock()
    sup._save_state = MagicMock()
    # Intentionally wipe as old close_all / reset did — ensure path restores
    original_reset = sup._reset_adverse_radar

    def wipe_then_keep(*args, **kwargs):
        # Call real reset; force_flat now passes keep_tv_sl=True via ensure_book_clean
        return original_reset(*args, **kwargs)

    with patch.object(sup, "_reset_adverse_radar", side_effect=wipe_then_keep):
        ok = PositionSupervisor._force_flat_before_open(sup, "TV OPEN [LONG] 铁律·先平后开")
    assert ok is True
    assert float(sup.tv_sl) == pytest.approx(tv_sl, abs=0.05)
    qty, meta = sup._resolve_entry_qty(1890.67)
    assert qty > 0
    assert meta.get("error") is None


def test_open_position_recovers_wiped_tv_sl():
    """If tv_sl was wiped before sizing, recover from _pending_open_tv_sl."""
    sup, client = _make_supervisor()
    tv_sl = 1874.3871690506
    sup.tv_sl = 0.0
    sup._tv_hard_sl_price = 0.0
    sup._pending_open_tv_sl = tv_sl
    sup._apply_tv_entry_context({
        "entry_type": "OPEN",
        "regime": 2,
        "risk_pct": 2.4,
        "leverage": 5,
        "qty_ratio": 1.0,
    })
    sup._cancel_binance_all_close_stops = MagicMock(return_value=0)
    # Avoid full protect path
    result = PositionSupervisor._open_position(sup, "LONG", 1890.67)
    assert float(sup.tv_sl) == pytest.approx(tv_sl)
    assert result.get("status") != "error" or result.get("reason") != "missing_tv_sl"
    client.place_market_order.assert_called()

