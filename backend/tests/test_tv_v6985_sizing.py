"""VPS sizing: OPEN by VPS formula; ADD by base_qty × TV qty_ratio."""

import pytest

from app.core.tv_entry_sizing import (
    compute_vps_add_qty,
    compute_vps_open_qty,
    effective_vps_risk_pct,
    max_add_times_for_regime,
    parse_tv_entry_fields,
    regime_add_qty_ratio,
    regime_margin_coeff,
    regime_scale,
    resolve_vps_entry_qty_eth,
)


def test_regime_scale_from_doc():
    assert regime_scale(1) == pytest.approx(0.55)
    assert regime_scale(2) == pytest.approx(0.75)
    assert regime_scale(3) == pytest.approx(0.95)
    assert regime_scale(4) == pytest.approx(1.33)


def test_regime_dynamic_add_defaults_match_pine():
    assert regime_add_qty_ratio(1) == pytest.approx(0.0)
    assert regime_add_qty_ratio(2) == pytest.approx(0.3)
    assert regime_add_qty_ratio(3) == pytest.approx(0.5)
    assert regime_add_qty_ratio(4) == pytest.approx(0.7)


def test_regime_max_add_times_match_pine():
    assert max_add_times_for_regime(1) == 1
    assert max_add_times_for_regime(2) == 2
    assert max_add_times_for_regime(3) == 2
    assert max_add_times_for_regime(4) == 3


def test_regime_margin_coeff_dual_symbol_spec():
    assert regime_margin_coeff(1) == pytest.approx(0.06)
    assert regime_margin_coeff(2) == pytest.approx(0.12)
    assert regime_margin_coeff(3) == pytest.approx(0.18)
    assert regime_margin_coeff(4) == pytest.approx(0.22)


@pytest.mark.parametrize(
    "regime,price,expected_qty",
    [
        (1, 2000.0, 0.75),    # 1000×6%×25 / 2000
        (2, 2000.0, 1.5),     # 1000×12%×25 / 2000
        (3, 2000.0, 2.25),    # 1000×18%×25 / 2000
        (4, 2000.0, 2.75),    # 1000×22%×25 / 2000
    ],
)
def test_vps_open_table_1000u(regime, price, expected_qty):
    qty, meta = compute_vps_open_qty(
        live_balance=1000.0,
        initial_principal=1000.0,
        price=price,
        tv_sl=1950.0,
        regime=regime,
        leverage=25,
        round_fn=lambda x: round(x, 3),
    )
    assert qty == pytest.approx(expected_qty, rel=0.02)
    assert meta["sizing_mode"] == "vps_open_margin_coeff"
    assert meta["position_value"] > 0


def test_vps_add_uses_tv_qty_ratio():
    qty, meta = compute_vps_add_qty(
        base_qty=1.496,
        tv_qty_ratio=0.7,
        round_fn=lambda x: round(x, 3),
        entry_type="PROFIT_ADD",
    )
    assert qty == pytest.approx(1.047, rel=0.01)
    assert meta["sizing_mode"] == "vps_add"
    assert meta["add_qty_ratio"] == pytest.approx(0.7)
    assert meta["qty_ratio_source"] == "tv_qty_ratio"


def test_vps_add_zero_ratio_returns_zero():
    qty, meta = compute_vps_add_qty(
        base_qty=1.496,
        tv_qty_ratio=0.0,
        round_fn=lambda x: round(x, 3),
        entry_type="PROFIT_ADD",
    )
    assert qty == 0.0
    assert meta["error"] == "zero_qty_ratio"


def test_resolve_add_uses_tv_qty_ratio():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="PROFIT_ADD",
        base_qty=1.496,
        price=2000.0,
        tv_sl=1950.0,
        regime=4,
        exchange_leverage=15,
        round_fn=lambda x: round(x, 3),
        tv_qty_ratio=0.7,
    )
    assert qty == pytest.approx(1.047, rel=0.01)
    assert meta["add_qty_ratio"] == pytest.approx(0.7)


def test_parse_tv_entry_fields_open_ignores_qty_ratio():
    fields = parse_tv_entry_fields({
        "action": "LONG",
        "entry_type": "OPEN",
        "risk_pct": 99.0,
        "regime": 2,
        "qty_ratio": 0.8,
    })
    assert fields["uses_vps_sizing"] is True
    assert fields["entry_type"] == "OPEN"
    assert fields["tv_qty_ratio_ignored"] is True
    assert "qty_ratio" not in fields


def test_parse_tv_entry_fields_add_reads_qty_ratio():
    fields = parse_tv_entry_fields({
        "action": "LONG",
        "entry_type": "PROFIT_ADD",
        "regime": 4,
        "qty_ratio": 0.7,
    })
    assert fields["qty_ratio"] == pytest.approx(0.7)
    assert fields["max_add_times"] == 3


def test_parse_tv_entry_fields_add_falls_back_to_regime_ratio():
    fields = parse_tv_entry_fields({
        "action": "LONG",
        "entry_type": "PYRAMID",
        "regime": 2,
    })
    assert fields["qty_ratio"] == pytest.approx(0.3)
    assert fields["qty_ratio_source"] == "regime_default"


def test_resolve_open_uses_margin_coeff():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="OPEN",
        base_qty=0,
        price=2000.0,
        tv_sl=1955.0,
        regime=1,
        exchange_leverage=25,
        round_fn=lambda x: round(x, 3),
    )
    assert qty > 0
    assert meta.get("sizing_mode") == "vps_open_margin_coeff"
    assert meta.get("margin_coeff") == pytest.approx(0.06)


def test_resolve_add_requires_base_qty():
    qty, meta = resolve_vps_entry_qty_eth(
        live_balance=1000.0,
        initial_principal=1000.0,
        entry_type="PYRAMID",
        base_qty=1.069,
        price=2000.0,
        tv_sl=1950.0,
        regime=3,
        exchange_leverage=15,
        round_fn=lambda x: round(x, 3),
        tv_qty_ratio=0.5,
    )
    assert qty == pytest.approx(0.535, rel=0.02)
    assert meta["add_qty"] == pytest.approx(0.535, rel=0.02)


def test_effective_risk_pct_cap():
    pct, meta = effective_vps_risk_pct(4)
    assert pct == pytest.approx(3.99)  # 3 * 1.33
    assert meta["risk_clamped"] is False
