"""Extreme webhook / sizing input robustness."""

import pytest

from app.core.tv_entry_sizing import compute_tv_entry_qty, parse_tv_entry_fields


def _base(**kw):
    defaults = dict(
        live_balance=100.0,
        initial_principal=100.0,
        price=2000.0,
        tv_sl=2000.0 - 1.5 * 20.0,
        tv_stop_loss=2000.0 - 20.0,
        tv_qty=0.05,
        symbol="ETHUSDT",
    )
    defaults.update(kw)
    return compute_tv_entry_qty(**defaults)


def test_qty_zero_rejected():
    q, m = _base(tv_qty=0)
    assert q == 0
    assert m.get("error") == "missing_tv_qty"


def test_qty_negative_rejected():
    q, m = _base(tv_qty=-1)
    assert q == 0
    assert m.get("error") == "missing_tv_qty"


def test_price_zero_rejected():
    q, m = _base(price=0)
    assert q == 0
    assert m.get("error") == "invalid_price"


def test_stop_equals_price_zero_dist():
    q, m = _base(tv_sl=2000.0, price=2000.0)
    assert q == 0
    assert m.get("error") in ("zero_stop_distance", "missing_stop")


def test_tv_stop_equals_price_zero_tv_dist():
    q, m = _base(tv_stop_loss=2000.0, price=2000.0)
    assert q == 0
    assert m.get("error") == "zero_tv_stop_distance"


def test_parse_tv_entry_fields_missing_qty():
    f = parse_tv_entry_fields({"price": 1, "action": "LONG"})
    assert f["tv_qty"] is None


def test_parse_tv_entry_fields_string_numbers():
    f = parse_tv_entry_fields({"qty": "0.03", "qty1": "0.01", "qty2": "0.01"})
    assert f["tv_qty"] == 0.03
    assert f["tv_qty1"] == 0.01


def test_short_direction_stop_above_entry():
    q, m = compute_tv_entry_qty(
        live_balance=100.0,
        initial_principal=100.0,
        price=2000.0,
        tv_sl=2000.0 + 1.5 * 20.0,
        tv_stop_loss=2000.0 + 20.0,
        tv_qty=0.05,
        symbol="ETHUSDT",
    )
    assert q > 0
    assert m.get("error") is None
