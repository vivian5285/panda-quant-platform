"""VPS dev checklist sizing: OPEN by price; ADD by base_qty × ADD_QTY_RATIO."""

import pytest

from app.core.tv_entry_sizing import (
    compute_vps_add_qty,
    compute_vps_open_qty,
    effective_vps_risk_pct,
    parse_tv_entry_fields,
    regime_scale,
    resolve_vps_entry_qty_eth,
)


def test_regime_scale_from_doc():
    assert regime_scale(1) == pytest.approx(0.55)
    assert regime_scale(2) == pytest.approx(0.75)
    assert regime_scale(3) == pytest.approx(0.95)
    assert regime_scale(4) == pytest.approx(1.33)


@pytest.mark.parametrize(
    "regime,price,expected_qty",
    [
        (1, 2000.0, 0.206),
        (2, 2000.0, 0.281),
        (3, 2000.0, 0.356),
        (4, 2000.0, 0.500),
    ],
)
def test_vps_open_table_1000u(regime, price, expected_qty):
    qty, meta = compute_vps_open_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=price,
        tv_sl=1950.0,
        regime=regime,
        leverage=5,
        round_fn=lambda x: round(x, 3),
    )
    assert qty == pytest.approx(expected_qty, rel=0.02)
    assert meta["sizing_mode"] == "vps_open"
    assert meta["position_value"] > 0


def test_vps_add_uses_base_qty_not_risk():
    qty, meta = compute_vps_add_qty(
        base_qty=0.5,
        round_fn=lambda x: round(x, 3),
        entry_type="PYRAMID",
    )
    assert qty == pytest.approx(0.25, rel=0.01)
    assert meta["sizing_mode"] == "vps_add"
    assert meta["add_qty_ratio"] == pytest.approx(0.5)


def test_vps_add_ignores_tv_qty_ratio():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="PROFIT_ADD",
        base_qty=0.5,
        price=2000.0,
        tv_sl=1950.0,
        regime=4,
        exchange_leverage=5,
        round_fn=lambda x: round(x, 3),
    )
    assert qty == pytest.approx(0.25, rel=0.01)
    assert meta["add_qty_ratio"] == pytest.approx(0.5)


def test_parse_tv_entry_fields_ignores_risk_pct():
    fields = parse_tv_entry_fields({
        "action": "LONG",
        "entry_type": "OPEN",
        "risk_pct": 99.0,
        "regime": 2,
    })
    assert fields["uses_vps_sizing"] is True
    assert fields["entry_type"] == "OPEN"


def test_resolve_open_never_uses_regime_margin():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="OPEN",
        base_qty=0,
        price=2000.0,
        tv_sl=1955.0,
        regime=1,
        exchange_leverage=5,
        round_fn=lambda x: round(x, 3),
    )
    assert qty > 0
    assert meta.get("sizing_mode") == "vps_open"
    assert "margin_pct" not in meta


def test_resolve_add_requires_base_qty():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="PYRAMID",
        base_qty=0.356,
        price=2000.0,
        tv_sl=1950.0,
        regime=3,
        exchange_leverage=5,
        round_fn=lambda x: round(x, 3),
    )
    assert qty == pytest.approx(0.178, rel=0.02)
    assert meta["add_qty"] == pytest.approx(0.178, rel=0.02)


def test_effective_risk_pct_cap():
    pct, meta = effective_vps_risk_pct(4)
    assert pct == pytest.approx(3.99)  # 3 * 1.33
    assert meta["risk_clamped"] is False
