"""Regression: astronomical TV.qty must not inflate fixed 1×-equity notional."""

import pytest

from app.core.tv_entry_sizing import (
    compute_tv_entry_qty,
    floor_qty,
)


def test_absurd_tv_qty_still_sizes_1x_equity():
    equity = 61.4
    price = 1932.4
    vps_stop = price - 1.5 * 15.6453
    tv_stop = 1916.7567275275
    tv_qty = 860680123.0

    qty, meta = compute_tv_entry_qty(
        live_balance=equity,
        initial_principal=equity,
        price=price,
        tv_sl=vps_stop,
        tv_stop_loss=tv_stop,
        tv_qty=tv_qty,
        symbol="ETHUSDT",
    )
    expected = floor_qty(equity / price, 0.001)  # 0.20×5 = 1× equity
    assert qty == pytest.approx(expected, abs=1e-9)
    assert meta["binding"] == "margin20_lev5"
    assert meta["notional_target"] == pytest.approx(equity)
    assert abs(float(meta["final_qty"]) - float(qty)) < 1e-12
    assert qty * price <= equity + 1e-6
    assert qty < 1.0


def test_tiny_tv_qty_does_not_override_1x():
    equity = 61.4
    price = 1932.4
    atr = 15.6453
    qty, meta = compute_tv_entry_qty(
        live_balance=equity,
        initial_principal=equity,
        price=price,
        tv_sl=price - 1.5 * atr,
        tv_stop_loss=price - 1.0 * atr,
        tv_qty=0.03,
        symbol="ETHUSDT",
    )
    expected = floor_qty(equity / price, 0.001)
    assert qty == pytest.approx(expected, abs=1e-9)
    assert meta["binding"] == "margin20_lev5"


def test_contract_equity_always_1x_notional():
    equity = 1719.0
    price = 1932.4
    qty, meta = compute_tv_entry_qty(
        live_balance=equity,
        initial_principal=100.0,
        price=price,
        tv_sl=1909.0,
        tv_stop_loss=1916.76,
        tv_qty=860680123.0,
        symbol="ETHUSDT",
    )
    assert meta["sizing_source"] == "contract_equity"
    assert meta["sizing_base"] == pytest.approx(equity)
    assert meta["notional_target"] == pytest.approx(equity)
    assert qty * price <= equity + 1e-6
    assert qty == pytest.approx(floor_qty(equity / price, 0.001), abs=1e-9)


def test_sizing_order_qty_identity_huge_and_small():
    for tv_qty in (860680123.0, 0.02, 0.03):
        qty, meta = compute_tv_entry_qty(
            live_balance=1719.0,
            initial_principal=1719.0,
            price=1932.4,
            tv_sl=1909.0,
            tv_stop_loss=1916.76,
            tv_qty=tv_qty,
            symbol="ETHUSDT",
        )
        assert qty == float(meta.get("final_qty") or 0)
        assert qty == pytest.approx(floor_qty(1719.0 / 1932.4, 0.001), abs=1e-9)
