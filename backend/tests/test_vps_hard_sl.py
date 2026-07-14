"""VPS autonomous hard stop — entry × regime % breathing space."""

import pytest

from app.core.vps_hard_sl import (
    HARD_SL_LIMIT_PCT,
    HARD_SL_STOP_LIMIT_OFFSET,
    REGIME_HARD_SL_PCT,
    compute_hard_sl_distance,
    compute_hard_sl_limit_price,
    compute_vps_hard_sl,
    hard_sl_pct,
)


def test_regime_pcts():
    assert hard_sl_pct(1) == pytest.approx(0.028)
    assert hard_sl_pct(2) == pytest.approx(0.039)
    assert hard_sl_pct(3) == pytest.approx(0.056)
    assert hard_sl_pct(4) == pytest.approx(0.083)
    assert REGIME_HARD_SL_PCT[4] == pytest.approx(0.083)


def test_distance_scales_with_entry():
    d1 = compute_hard_sl_distance(1000.0, 3)
    d2 = compute_hard_sl_distance(2000.0, 3)
    assert d1 == pytest.approx(56.0, rel=0.001)
    assert d2 == pytest.approx(112.0, rel=0.001)
    assert d2 == pytest.approx(2 * d1, rel=0.001)


def test_regime2_long_example():
    meta = compute_vps_hard_sl(1819.0, "LONG", 16.65, 2)
    assert meta["hard_sl_pct"] == pytest.approx(0.039)
    assert meta["sl_distance"] == pytest.approx(1819.0 * 0.039, rel=0.001)
    assert meta["stop_price"] == pytest.approx(1819.0 * (1 - 0.039), rel=0.001)
    assert meta["source"] == "vps_computed"
    assert meta["method"] == "entry_pct"


def test_regime1_short_example():
    entry = 1777.33
    meta = compute_vps_hard_sl(entry, "SHORT", 15.78, 1)
    assert meta["sl_distance"] == pytest.approx(entry * 0.028, rel=0.001)
    assert meta["stop_price"] == pytest.approx(entry * (1 + 0.028), rel=0.001)


def test_all_regimes_monotonic_pct_distance():
    entry = 1800.0
    dists = [compute_hard_sl_distance(entry, r) for r in (1, 2, 3, 4)]
    assert dists == sorted(dists)
    assert dists[0] == pytest.approx(entry * 0.028, rel=0.001)
    assert dists[3] == pytest.approx(entry * 0.083, rel=0.001)


def test_atr_ignored_same_stop():
    a = compute_vps_hard_sl(1800.0, "LONG", atr=10.0, regime=3)
    b = compute_vps_hard_sl(1800.0, "LONG", atr=50.0, regime=3)
    assert a["stop_price"] == b["stop_price"]


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


def test_short_stop_above_entry():
    meta = compute_vps_hard_sl(1819.0, "SHORT", 16.65, 2)
    assert meta["stop_price"] > 1819.0
    assert meta["limit_price"] > meta["stop_price"]


def test_tv_sl_reference_only():
    meta = compute_vps_hard_sl(2000.0, "LONG", 30.0, 3, tv_sl_reference=1900.0)
    assert meta["tv_sl_reference"] == 1900.0
    assert meta["stop_price"] == pytest.approx(2000.0 * (1 - 0.056), rel=0.001)
    assert meta["stop_price"] != 1900.0
