"""RISK20 sizing — equity×0.20/stop_dist ∩ equity×5/price ∩ TV.qty."""

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


def test_risk20_stop_and_tv_qty_cap():
    # equity 1000, risk 20% = 200; stop dist 100 → qty_by_risk=2
    # notional 5000/3300 ≈ 1.515 → binds notional
    # tv_qty 1.0 → final 1.0
    qty, meta = compute_tv_entry_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=3300.0,
        tv_sl=3200.0,
        tv_qty=1.0,
        symbol="ETHUSDT",
    )
    assert qty == pytest.approx(1.0, abs=1e-9)
    assert meta["sizing_mode"] == SIZING_MODE
    assert meta["binding"] == "tv_qty_cap"


def test_stop_risk_binds_when_stop_far():
    # stop dist 20 → risk qty = 200/20 = 10; notional 5000/3300≈1.515 → notional binds
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=3300, tv_sl=3280, tv_qty=10,
        symbol="ETHUSDT",
    )
    assert qty == pytest.approx(1.515, abs=0.001)
    assert meta["binding"] == "notional_cap"


def test_missing_stop_refuses():
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=3300, tv_sl=0, tv_qty=1,
        symbol="ETHUSDT",
    )
    assert qty == 0
    assert meta.get("error") == "missing_stop"


def test_missing_tv_qty_refuses():
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=3300, tv_sl=3200, tv_qty=None,
        symbol="ETHUSDT",
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
        base_qty=1, price=3300, tv_sl=3200, exchange_leverage=5,
        round_fn=lambda x: x, symbol="ETHUSDT", tv_qty=1.0,
    )
    assert qty == 0
    assert meta.get("error") == "add_disabled"
