"""RISK20 sizing — equity×0.20/vps_dist ∩ equity×5/price ∩ (TV.qty×tv_dist/vps_dist)."""

import pytest

from app.core.tv_entry_sizing import (
    SIZING_MODE,
    compute_tv_entry_qty,
    compute_vps_add_qty,
    floor_qty,
    max_add_times_for_regime,
    parse_tv_entry_fields,
    regime_add_qty_ratio,
    resolve_vps_entry_qty_eth,
)


def test_floor_qty_eth_step():
    assert floor_qty(0.6705, 0.001) == pytest.approx(0.670)
    assert floor_qty(1.4599, 0.001) == pytest.approx(1.459)


def test_risk20_stop_and_tv_qty_cap_when_adj_is_one():
    # VPS stop == TV stop → adj=1; tv_qty 1.0 binds
    qty, meta = compute_tv_entry_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=3300.0,
        tv_sl=3200.0,
        tv_stop_loss=3200.0,
        tv_qty=1.0,
        symbol="ETHUSDT",
    )
    assert qty == pytest.approx(1.0, abs=1e-9)
    assert meta["sizing_mode"] == SIZING_MODE
    assert meta["adjust_coef"] == pytest.approx(1.0)
    assert meta["binding"] == "tv_qty_cap_adjusted"


def test_tv_qty_scaled_by_stop_distance_ratio():
    # VPS initialStop 3150 → dist 150; TV stop 3200 → dist 100; adj=100/150=2/3
    # risk=200/150≈1.333; notional≈1.515; tv_adj=1.0*(2/3)≈0.666 → binds tv_adj
    qty, meta = compute_tv_entry_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=3300.0,
        tv_sl=3150.0,
        tv_stop_loss=3200.0,
        tv_qty=1.0,
        symbol="ETHUSDT",
    )
    assert meta["adjust_coef"] == pytest.approx(100.0 / 150.0)
    assert meta["candidate_qty_by_tv_adj"] == pytest.approx(2.0 / 3.0, abs=1e-6)
    assert qty == pytest.approx(0.666, abs=0.001)
    assert meta["binding"] == "tv_qty_cap_adjusted"
    # At VPS stop, $ risk ≈ qty * 150 ≈ 100 = 10%? Wait: 0.666*150≈100 = risk budget 200? 
    # 0.666*150 = 99.9 ≈ half of 200 because tv_adj binds below risk qty.
    # If filled at risk qty without adj: 1.333*150=200. With adj: ~100 loss if TV dist was used
    # Actual loss at VPS stop with adj qty: 0.666*150≈100 — within 20% of 1000? 100 < 200 yes.


def test_stop_risk_binds_when_stop_far():
    # stop dist 20 → risk qty = 200/20 = 10; notional 5000/3300≈1.515 → notional binds
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=3300, tv_sl=3280,
        tv_stop_loss=3280, tv_qty=10, symbol="ETHUSDT",
    )
    assert qty == pytest.approx(1.515, abs=0.001)
    assert meta["binding"] == "notional_cap"


def test_missing_stop_refuses():
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=3300, tv_sl=0,
        tv_stop_loss=3200, tv_qty=1, symbol="ETHUSDT",
    )
    assert qty == 0
    assert meta.get("error") == "missing_stop"


def test_missing_tv_stop_loss_refuses():
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=3300, tv_sl=3200,
        tv_stop_loss=None, tv_qty=1, symbol="ETHUSDT",
    )
    assert qty == 0
    assert meta.get("error") == "missing_tv_stop_loss"


def test_missing_tv_qty_refuses():
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=3300, tv_sl=3200,
        tv_stop_loss=3200, tv_qty=None, symbol="ETHUSDT",
    )
    assert qty == 0
    assert meta.get("error") == "missing_tv_qty"


def test_add_disabled():
    assert regime_add_qty_ratio(3) == 0.0
    assert max_add_times_for_regime(3) == 0
    qty, meta = compute_vps_add_qty(live_balance=1000, price=3300)
    assert qty == 0
    assert meta.get("error") == "add_disabled"


def test_parse_fields_risk_mode():
    f = parse_tv_entry_fields({"qty": 1.5, "action": "LONG"})
    assert f["sizing_mode"] == SIZING_MODE
    assert f["tv_qty"] == 1.5


def test_resolve_eth_pyramid_disabled():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000, initial_principal=1000, entry_type="PYRAMID",
        base_qty=1, price=3300, tv_sl=3200, tv_stop_loss=3200,
        exchange_leverage=5, round_fn=lambda x: x, symbol="ETHUSDT", tv_qty=1.0,
    )
    assert qty == 0
    assert meta.get("error") == "add_disabled"
