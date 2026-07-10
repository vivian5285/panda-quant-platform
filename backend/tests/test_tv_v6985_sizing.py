"""VPS final sizing: OPEN by sl-distance; ADD by base_qty × qty_ratio."""

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
    assert regime_scale(4) == pytest.approx(1.30)


@pytest.mark.parametrize(
    "regime,price,tv_sl,expected_qty",
    [
        (1, 2000.0, 1955.0, 1.833),   # 82.5 / 45
        (2, 2000.0, 1947.5, 2.143),   # 112.5 / 52.5
        (3, 2000.0, 1945.0, 2.591),   # 142.5 / 55
        (4, 2000.0, 1937.5, 3.12),    # 195 / 62.5
    ],
)
def test_vps_open_table_1000u(regime, price, tv_sl, expected_qty):
    qty, meta = compute_vps_open_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=price,
        tv_sl=tv_sl,
        regime=regime,
        leverage=5,
        round_fn=lambda x: round(x, 3),
    )
    assert qty == pytest.approx(expected_qty, rel=0.02)
    assert meta["sizing_mode"] == "vps_open"
    assert meta["order_amount"] > 0


def test_vps_add_uses_base_qty_not_risk():
    qty, meta = compute_vps_add_qty(
        base_qty=1.83,
        qty_ratio=0.5,
        round_fn=lambda x: round(x, 3),
        entry_type="PYRAMID",
    )
    assert qty == pytest.approx(0.915, rel=0.01)
    assert meta["sizing_mode"] == "vps_add"
    assert meta["base_qty"] == pytest.approx(1.83)


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
        qty_ratio=1.0,
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
        base_qty=2.0,
        qty_ratio=0.5,
        price=2000.0,
        tv_sl=1950.0,
        regime=3,
        exchange_leverage=5,
        round_fn=lambda x: round(x, 3),
    )
    assert qty == pytest.approx(1.0)
    assert meta["add_qty"] == 1.0


def test_effective_risk_pct_cap():
    pct, meta = effective_vps_risk_pct(4)
    assert pct == pytest.approx(3.9)  # 3 * 1.30
    assert meta["risk_clamped"] is False
