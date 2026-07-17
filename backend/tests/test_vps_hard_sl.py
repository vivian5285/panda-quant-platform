"""VPS autonomous hard stop — entry × regime % (ETH/XAU shared)."""

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


def test_regime_pct_table():
    assert REGIME_HARD_SL_PCT[1] == pytest.approx(0.0278)
    assert REGIME_HARD_SL_PCT[2] == pytest.approx(0.0389)
    assert REGIME_HARD_SL_PCT[3] == pytest.approx(0.0556)
    assert REGIME_HARD_SL_PCT[4] == pytest.approx(0.0833)
    assert hard_sl_pct(3) == pytest.approx(0.0556)


def test_eth_reference_distances_at_1800():
    """@1800: R1≈50 / R2≈70 / R3≈100 / R4≈150."""
    assert compute_hard_sl_distance(1800.0, 1) == pytest.approx(50.04, abs=0.1)
    assert compute_hard_sl_distance(1800.0, 2) == pytest.approx(70.02, abs=0.1)
    assert compute_hard_sl_distance(1800.0, 3) == pytest.approx(100.08, abs=0.1)
    assert compute_hard_sl_distance(1800.0, 4) == pytest.approx(149.94, abs=0.1)


def test_xau_same_pct_as_eth():
    """XAU uses same entry-% — absolute distance scales with price."""
    eth = compute_vps_hard_sl(1800.0, "SHORT", atr=15.16, regime=3)
    xau = compute_vps_hard_sl(4004.27, "SHORT", atr=15.16, regime=3)
    assert eth["hard_sl_pct"] == pytest.approx(xau["hard_sl_pct"])
    assert eth["method"] == "entry_pct"
    assert xau["stop_price"] == pytest.approx(4004.27 * (1 + 0.0556), abs=0.05)
    # Live 2026-07-17 XAU short hung ≈4226.91
    assert xau["stop_price"] == pytest.approx(4226.91, abs=0.5)


def test_regime2_long_example():
    meta = compute_vps_hard_sl(1819.0, "LONG", 16.65, 2)
    assert meta["sl_distance"] == pytest.approx(1819.0 * 0.0389, rel=0.001)
    assert meta["stop_price"] == pytest.approx(1819.0 * (1 - 0.0389), rel=0.001)
    assert meta["source"] == "vps_computed"
    assert meta["method"] == "entry_pct"


def test_regime1_short_example():
    entry = 1777.33
    meta = compute_vps_hard_sl(entry, "SHORT", atr=15.78, regime=1)
    assert meta["sl_distance"] == pytest.approx(entry * 0.0278, rel=0.001)
    assert meta["stop_price"] == pytest.approx(entry * (1 + 0.0278), rel=0.001)


def test_all_regimes_monotonic_distance():
    dists = [compute_hard_sl_distance(1800.0, r) for r in (1, 2, 3, 4)]
    assert dists == sorted(dists)


def test_atr_ignored():
    a = compute_vps_hard_sl(2000.0, "LONG", atr=10.0, regime=3)
    b = compute_vps_hard_sl(2000.0, "LONG", atr=50.0, regime=3)
    assert a["stop_price"] == pytest.approx(b["stop_price"])


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


def test_tv_sl_reference_only():
    meta = compute_vps_hard_sl(2000.0, "LONG", 30.0, 3, tv_sl_reference=1900.0)
    assert meta["tv_sl_reference"] == pytest.approx(1900.0)
    assert meta["stop_price"] == pytest.approx(2000.0 * (1 - 0.0556), rel=0.001)
