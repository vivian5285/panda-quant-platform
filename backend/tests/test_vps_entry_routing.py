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
    # VPS ATR=100 → initialStop=3150, vps_dist=150
    # TV stop_loss=3200 (1.0×ATR) → tv_dist=100; adj=2/3
    # risk≈1.333; notional≈1.515; tv_adj≈0.666 → final 0.666
    atr = 100.0
    sup.current_atr = atr
    sup.initial_atr = atr
    sup._pending_open_side = "LONG"
    sup._tv_entry_fields = {"tv_qty": 1.0, "sizing_mode": SIZING_MODE, "tv_qty1": 0.3, "tv_qty2": 0.3}
    sup._pull_vps_market_indicators = MagicMock(return_value={"atr": atr, "adx": 25.0})
    sup.tv_sl = 3200.0
    sup._pending_open_tv_sl = 3200.0
    sup.tv_tps = [3400.0, 3500.0, 3600.0]
    sup.on_trade_open = MagicMock(return_value=1)
    sup._protect_and_monitor = MagicMock()
    sup._sync_tv_hard_stop = MagicMock(return_value={"aligned": True, "stop_price": 3150.0})
    sup._enforce_regime_cap_alignment = MagicMock(return_value={})
    return sup, client


def test_open_uses_risk20_formula():
    sup, client = _make_supervisor()
    qty, meta = sup._resolve_entry_qty(3300.0)
    assert meta["sizing_mode"] == SIZING_MODE
    assert meta["adjust_coef"] == pytest.approx(100.0 / 150.0)
    assert qty == pytest.approx(0.666, abs=0.001)
    assert meta["binding"] == "tv_qty_cap_adjusted"


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
        tv_stop_loss=3200,
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
    """先平后开后仍用 RISK20 算仓（需 VPS stop + TV stop_loss + tv_qty）。"""
    sup, _ = _make_supervisor()
    tv_sl = 3200.0
    sup.tv_sl = tv_sl
    sup._tv_hard_sl_price = tv_sl
    sup._pending_open_tv_sl = tv_sl
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
    # Re-arm sizing inputs after flat
    atr = 100.0
    sup.tv_sl = tv_sl
    sup._pending_open_tv_sl = tv_sl
    sup.current_atr = atr
    sup.initial_atr = atr
    sup._pending_open_side = "LONG"
    sup._tv_entry_fields = {"tv_qty": 1.0, "sizing_mode": SIZING_MODE}
    sup._pull_vps_market_indicators = MagicMock(return_value={"atr": atr, "adx": 25.0})
    qty, meta = sup._resolve_entry_qty(3300.0)
    assert qty == pytest.approx(0.666, abs=0.001)
    assert meta.get("error") is None


def test_force_flat_close_fail_retries_then_pauses():
    """平仓未归零：1/3/6 重试后中止开仓并暂停（严禁不明仓位继续开新仓）。"""
    sup, _ = _make_supervisor()
    sup.tv_sl = 3200.0
    sup._tv_hard_sl_price = 3200.0
    sup._get_active_position = MagicMock(
        return_value={"size": 1.0, "side": "SHORT", "entry_price": 3300.0},
    )
    sup.position_manager = MagicMock()
    sup.position_manager.get_position.return_value = {"positionAmt": -1.0, "entryPrice": 3300.0}
    sup._purge_defense_orders_on_flat = MagicMock()
    sup._cancel_all_verified = MagicMock()
    sup._close_all = MagicMock()
    sup._wait_until_flat = MagicMock(return_value=False)
    sup._alert = MagicMock()
    sup._pause_trading = MagicMock()
    sup._reconcile_live_vs_book = MagicMock(return_value={"ok": False})
    sup._save_state = MagicMock()
    with patch("app.core.position_supervisor.time.sleep", return_value=None):
        ok = PositionSupervisor._force_flat_before_open(sup, "TV OPEN [LONG] 铁律·先平后开")
    assert ok is False
    assert sup._close_all.call_count == 3
    sup._pause_trading.assert_called()
    types = [c.args[1] for c in sup._alert.call_args_list]
    assert "FLIP_CLEAN_ABORT" in types


def test_force_flat_dirty_book_after_flat_aborts():
    """仓位已平但挂单残留：不得继续开仓。"""
    sup, _ = _make_supervisor()
    sup.tv_sl = 3200.0
    sup._get_active_position = MagicMock(
        return_value={"size": 1.0, "side": "LONG", "entry_price": 3300.0},
    )
    sup._purge_defense_orders_on_flat = MagicMock()
    sup._cancel_all_verified = MagicMock()
    sup._close_all = MagicMock()
    # Flat succeeds on first wait; dirty book must still abort open
    dirty = {
        "ok": False, "orders_after": 2, "orders_before": 2, "rounds": 3, "reason": "x",
    }
    clean = MagicMock(return_value=dirty)
    recon = MagicMock(return_value={"ok": True})
    sup._wait_until_flat = MagicMock(return_value=True)
    sup._alert = MagicMock()
    sup._pause_trading = MagicMock()
    with patch.object(sup, "_ensure_book_clean_before_open", clean), \
         patch.object(sup, "_reconcile_live_vs_book", recon), \
         patch("app.core.position_supervisor.time.sleep", return_value=None):
        ok = PositionSupervisor._force_flat_before_open(sup, "TV OPEN [LONG]")
    assert ok is False
    sup._pause_trading.assert_called()
    types = [c.args[1] for c in sup._alert.call_args_list]
    assert "FLIP_CLEAN_ABORT" in types


def test_atr_invalid_falls_back_when_tv_stop_present():
    """ATR≤0 且有 TV stop → 应急降级用 TV 隐含 ATR，不永久拒单。"""
    sup, _ = _make_supervisor()
    sup.current_atr = 0.0
    sup._pull_vps_market_indicators = MagicMock(return_value={"atr": 0.0, "atr_series": []})
    sup._pause_trading = MagicMock()
    sup._alert = MagicMock()
    qty, meta = sup._resolve_entry_qty(3300.0)
    assert qty > 0
    assert meta.get("atr_source") == "tv_emergency_fallback"
    assert meta.get("atr_fallback") is True
    # TV implied = |3300-3200|/1.0 = 100
    assert meta.get("sizing_atr") == pytest.approx(100.0)
    types = [c.args[1] for c in sup._alert.call_args_list]
    assert "ATR_FALLBACK" in types
    assert getattr(sup, "_atr_fallback_pending_pause", False) is True


def test_atr_invalid_still_rejects_without_tv_stop():
    """无 TV stop 可反推时，ATR无效仍拒开仓（禁止静默换源）。"""
    sup, _ = _make_supervisor()
    sup.tv_sl = 0.0
    sup._pending_open_tv_sl = 0.0
    sup._tv_hard_sl_price = 0.0
    sup.current_atr = 0.0
    sup._pull_vps_market_indicators = MagicMock(return_value={"atr": 0.0, "atr_series": []})
    sup._pause_trading = MagicMock()
    sup._alert = MagicMock()
    qty, meta = sup._resolve_entry_qty(3300.0)
    assert qty == 0
    assert meta.get("error") == "atr_invalid"
    sup._pause_trading.assert_not_called()


def test_atr_anomaly_falls_back_when_tv_stop_present():
    """当前 ATR < 中位数×0.3 → 降级用 TV 隐含，不静默拒单。"""
    from app.core.market_indicators import evaluate_atr_sanity

    series = [100.0] * 50
    sanity = evaluate_atr_sanity(20.0, series, lookback=50, floor_ratio=0.3)
    assert sanity["ok"] is False
    assert sanity["error"] == "atr_anomaly"

    sup, _ = _make_supervisor()
    atr = 20.0
    series = [100.0] * 50
    series[-1] = 20.0
    sup.current_atr = atr
    # TV stop 3200 @ entry 3300 → implied 100
    sup._pull_vps_market_indicators = MagicMock(
        return_value={"atr": atr, "atr_series": series, "adx": 25.0}
    )
    sup._pause_trading = MagicMock()
    qty, meta = sup._resolve_entry_qty(3300.0)
    assert qty > 0
    assert meta.get("atr_source") == "tv_emergency_fallback"
    assert meta.get("sizing_atr") == pytest.approx(100.0)


def test_open_position_recovers_wiped_tv_sl():
    """If tv_sl was wiped before sizing, recover from _pending_open_tv_sl."""
    sup, client = _make_supervisor()
    tv_sl = 3200.0
    sup.tv_sl = 0.0
    sup._tv_hard_sl_price = 0.0
    sup._pending_open_tv_sl = tv_sl
    # Provide atr_series so median check passes
    atr = 100.0
    series = [100.0] * 20
    series.append(atr)
    sup._pull_vps_market_indicators = MagicMock(
        return_value={"atr": atr, "adx": 25.0, "atr_series": series}
    )
    sup._cancel_binance_all_close_stops = MagicMock(return_value=0)
    result = PositionSupervisor._open_position(sup, "LONG", 3300.0)
    assert float(sup.tv_sl) == pytest.approx(tv_sl)
    assert result.get("status") != "error" or result.get("reason") != "missing_tv_sl"
    client.place_market_order.assert_called()
