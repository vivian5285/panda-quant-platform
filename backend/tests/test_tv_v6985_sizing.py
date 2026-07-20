"""TV risk-formula sizing — equity × risk_pct / |price-tv_sl|, capped by leverage & 50k."""

import pytest

from app.core.tv_entry_sizing import (
    compute_tv_entry_qty,
    compute_vps_add_qty,
    compute_vps_open_qty,
    floor_qty,
    max_add_times_for_regime,
    parse_tv_entry_fields,
    regime_add_qty_ratio,
    resolve_vps_entry_qty_eth,
)


def test_floor_qty_eth_step():
    assert floor_qty(0.6705, 0.001) == pytest.approx(0.670)
    assert floor_qty(1.4599, 0.001) == pytest.approx(1.459)


def test_spec_table_1000u_eth_1892():
    """User spec table: equity 1000, ETH@1892.43, qty_ratio=1."""
    price = 1892.43
    cases = [
        # risk_pct, stop_distance, expected_qty
        (0.81, 12.08, 0.67),
        (1.35, 14.09, 0.96),
        (2.03, 14.02, 1.45),
        (2.70, 15.94, 1.69),
    ]
    for risk_pct, dist, expected in cases:
        tv_sl = price - dist  # LONG
        qty, meta = compute_tv_entry_qty(
            live_balance=1000.0,
            initial_principal=1000.0,
            price=price,
            tv_sl=tv_sl,
            risk_pct=risk_pct,
            leverage=25,
            qty_ratio=1.0,
            symbol="ETHUSDT",
        )
        assert qty == pytest.approx(expected, abs=0.01), (risk_pct, qty, meta)
        assert meta["sizing_mode"] == "tv_risk_formula"
        assert meta["binding"] == "theoretical"


def test_principal_scales_linear():
    price, dist, risk = 1892.43, 14.02, 2.03
    tv_sl = price - dist
    q1, _ = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=price, tv_sl=tv_sl,
        risk_pct=risk, leverage=25, qty_ratio=1.0, symbol="ETHUSDT",
    )
    q2, _ = compute_tv_entry_qty(
        live_balance=2000, initial_principal=2000, price=price, tv_sl=tv_sl,
        risk_pct=risk, leverage=25, qty_ratio=1.0, symbol="ETHUSDT",
    )
    assert q2 == pytest.approx(q1 * 2, abs=0.02)


def test_add_uses_same_formula_times_qty_ratio():
    price, dist, risk = 1892.43, 14.02, 2.03
    tv_sl = price - dist
    open_qty, _ = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=price, tv_sl=tv_sl,
        risk_pct=risk, leverage=25, qty_ratio=1.0, symbol="ETHUSDT",
    )
    add_qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=price, tv_sl=tv_sl,
        risk_pct=risk, leverage=25, qty_ratio=0.5, entry_type="PYRAMID",
        symbol="ETHUSDT",
    )
    assert open_qty == pytest.approx(1.45, abs=0.01)
    assert add_qty == pytest.approx(open_qty * 0.5, abs=0.02)
    assert meta["entry_type"] == "PYRAMID"


def test_leverage_and_hard_cap_bind():
    # Tiny stop → huge theoretical; leverage/hard should bind
    qty, meta = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000,
        price=2000, tv_sl=1999.5, risk_pct=50.0, leverage=5,
        qty_ratio=1.0, symbol="ETHUSDT",
    )
    # leverage_limit = 1000*5/2000 = 2.5; hard = 50000/2000 = 25
    assert meta["leverage_limit_qty"] == pytest.approx(2.5)
    assert qty == pytest.approx(2.5, abs=0.001)
    assert meta["binding"] == "leverage"


def test_missing_risk_pct_or_tv_sl():
    q, m = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=1900, tv_sl=1880,
        risk_pct=0, leverage=25, qty_ratio=1.0,
    )
    assert q == 0 and m["error"] == "missing_risk_pct"
    q2, m2 = compute_tv_entry_qty(
        live_balance=1000, initial_principal=1000, price=1900, tv_sl=0,
        risk_pct=2.0, leverage=25, qty_ratio=1.0,
    )
    assert q2 == 0 and m2["error"] == "missing_tv_sl"


def test_parse_tv_entry_fields_reads_tv_params():
    fields = parse_tv_entry_fields({
        "action": "LONG",
        "entry_type": "OPEN",
        "risk_pct": 2.03,
        "regime": 3,
        "qty_ratio": 1.0,
        "leverage": 25,
    })
    assert fields["risk_pct"] == pytest.approx(2.03)
    assert fields["leverage"] == 25
    assert fields["qty_ratio"] == pytest.approx(1.0)
    assert fields["tv_qty_ratio_ignored"] is False


def test_parse_add_qty_ratio():
    fields = parse_tv_entry_fields({
        "entry_type": "PROFIT_ADD",
        "regime": 3,
        "qty_ratio": 0.4,
        "risk_pct": 2.03,
        "leverage": 25,
    })
    assert fields["qty_ratio"] == pytest.approx(0.4)
    assert fields["max_add_times"] == max_add_times_for_regime(3)


def test_parse_add_falls_back_regime_ratio():
    fields = parse_tv_entry_fields({"entry_type": "PYRAMID", "regime": 2, "risk_pct": 1.35, "leverage": 25})
    assert fields["qty_ratio"] == pytest.approx(regime_add_qty_ratio(2))
    assert fields["qty_ratio_source"] == "regime_default"


def test_resolve_open_tv_formula():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="OPEN",
        base_qty=0,
        price=1892.43,
        tv_sl=1892.43 - 14.02,
        regime=3,
        exchange_leverage=25,
        round_fn=lambda x: x,
        risk_pct=2.03,
        tv_qty_ratio=1.0,
        symbol="ETHUSDT",
    )
    assert qty == pytest.approx(1.45, abs=0.01)
    assert meta["sizing_mode"] == "tv_risk_formula"


def test_resolve_add_tv_formula():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="PYRAMID",
        base_qty=1.45,
        price=1892.43,
        tv_sl=1892.43 - 14.02,
        regime=3,
        exchange_leverage=25,
        round_fn=lambda x: x,
        tv_qty_ratio=0.5,
        risk_pct=2.03,
        symbol="ETHUSDT",
    )
    assert qty == pytest.approx(0.72, abs=0.02)
    assert meta["sizing_mode"] == "tv_risk_formula"


def test_compute_vps_open_qty_wrapper():
    qty, meta = compute_vps_open_qty(
        live_balance=1000, initial_principal=1000,
        price=1892.43, tv_sl=1892.43 - 12.08, regime=1, leverage=25,
        round_fn=lambda x: x, risk_pct=0.81, symbol="ETHUSDT",
    )
    assert qty == pytest.approx(0.67, abs=0.01)


def test_add_zero_ratio():
    qty, meta = compute_vps_add_qty(
        base_qty=1.45, tv_qty_ratio=0.0, round_fn=lambda x: x,
        live_balance=1000, initial_principal=1000,
        price=1892.43, tv_sl=1880, risk_pct=2.03, leverage=25,
    )
    assert qty == 0.0
    assert meta["error"] == "zero_qty_ratio"
