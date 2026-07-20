"""Hard stop — TradingView tv_sl authoritative (VPS entry% / wide SL deleted)."""

import pytest

from app.core.vps_hard_sl import (
    HARD_SL_LIMIT_PCT,
    HARD_SL_STOP_LIMIT_OFFSET,
    compute_hard_sl_limit_price,
    compute_vps_hard_sl,
)


def test_tv_sl_is_authoritative_stop():
    meta = compute_vps_hard_sl(2000.0, "LONG", 30.0, 3, tv_sl_reference=1900.0)
    assert meta["source"] == "tv_sl"
    assert meta["method"] == "tv_hard_sl"
    assert meta["stop_price"] == pytest.approx(1900.0)
    assert meta["tv_sl_reference"] == pytest.approx(1900.0)
    # Must NOT use entry×regime legacy wide stop
    vps_legacy = 2000.0 * (1 - 0.0556)
    assert abs(float(meta["stop_price"]) - vps_legacy) > 5.0


def test_tv_sl_short():
    meta = compute_vps_hard_sl(1800.0, "SHORT", atr=15.0, regime=4, tv_sl_reference=1860.46)
    assert meta["stop_price"] == pytest.approx(1860.46)
    assert meta["source"] == "tv_sl"


def test_missing_tv_sl_no_vps_fallback():
    meta = compute_vps_hard_sl(2000.0, "LONG", 30.0, 3)
    assert meta["stop_price"] == 0.0
    assert meta.get("error") == "no_tv_sl"
    assert meta["source"] == "missing_tv_sl"


def test_atr_ignored_when_tv_present():
    a = compute_vps_hard_sl(2000.0, "LONG", atr=10.0, regime=3, tv_sl_reference=1900.0)
    b = compute_vps_hard_sl(2000.0, "LONG", atr=50.0, regime=3, tv_sl_reference=1900.0)
    assert a["stop_price"] == pytest.approx(b["stop_price"])


def test_no_buffer_on_tv_sl_trigger():
    """Stop-Limit 限价可有微小偏移，但触发价必须等于 tv_sl 原值。"""
    meta = compute_vps_hard_sl(1892.43, "LONG", tv_sl_reference=1878.41)
    assert meta["stop_price"] == pytest.approx(1878.41)
    assert meta["limit_price"] < meta["stop_price"]


def test_stop_limit_pct_long():
    stop = 1748.06
    lim = compute_hard_sl_limit_price(stop, "LONG")
    assert lim == pytest.approx(stop * (1 - HARD_SL_LIMIT_PCT), abs=0.05)
    assert lim < stop


def test_stop_limit_pct_short():
    stop = 1827.09
    lim = compute_hard_sl_limit_price(stop, "SHORT")
    assert lim == pytest.approx(stop * (1 + HARD_SL_LIMIT_PCT), abs=0.05)
    assert lim > stop


def test_stop_limit_explicit_offset():
    assert compute_hard_sl_limit_price(1800.0, "LONG", offset=HARD_SL_STOP_LIMIT_OFFSET) == pytest.approx(
        1800.0 - HARD_SL_STOP_LIMIT_OFFSET, rel=0.001,
    )
