"""VPS autonomous hard stop — ATR × regime breathing space (v6.9.103)."""

import pytest

from app.core.vps_hard_sl import (
    HARD_SL_LIMIT_PCT,
    HARD_SL_STOP_LIMIT_OFFSET,
    REGIME_HARD_SL,
    compute_hard_sl_distance,
    compute_hard_sl_limit_price,
    compute_vps_hard_sl,
    hard_sl_final_multiplier,
    hard_sl_pct,
)


def test_regime_multipliers():
    assert hard_sl_final_multiplier(1) == pytest.approx(0.90)
    assert hard_sl_final_multiplier(2) == pytest.approx(1.89)
    assert hard_sl_final_multiplier(3) == pytest.approx(3.30)
    assert hard_sl_final_multiplier(4) == pytest.approx(6.00)
    assert REGIME_HARD_SL[4]["regime_multiplier"] == pytest.approx(4.8)


def test_regime4_breathing_space_at_reference_atr():
    dist = compute_hard_sl_distance(1800.0, 4, atr=16.65)
    assert dist == pytest.approx(99.9, rel=0.01)


def test_regime2_long_example():
    meta = compute_vps_hard_sl(1819.0, "LONG", 16.65, 2)
    assert meta["sl_distance"] == pytest.approx(31.47, rel=0.02)
    assert meta["stop_price"] == pytest.approx(1787.53, rel=0.01)
    assert meta["source"] == "vps_computed"
    assert meta["method"] == "atr_regime"


def test_regime1_short_example():
    entry = 1777.33
    atr = 15.78
    meta = compute_vps_hard_sl(entry, "SHORT", atr, 1)
    assert meta["sl_distance"] == pytest.approx(atr * 0.90, rel=0.001)
    assert meta["stop_price"] == pytest.approx(entry + atr * 0.90, rel=0.001)


def test_all_regimes_monotonic_distance():
    atr = 16.65
    dists = [compute_hard_sl_distance(1800.0, r, atr=atr) for r in (1, 2, 3, 4)]
    assert dists == sorted(dists)


def test_atr_scales_distance_not_entry_pct():
    """Same ATR → same distance on ETH and XAU (not entry×%)."""
    eth = compute_vps_hard_sl(1800.0, "SHORT", atr=15.16, regime=3)
    xau = compute_vps_hard_sl(4004.27, "SHORT", atr=15.16, regime=3)
    assert eth["sl_distance"] == pytest.approx(xau["sl_distance"], rel=0.001)
    assert eth["sl_distance"] == pytest.approx(15.16 * 3.30, rel=0.001)
    # Must NOT be entry×5.56% (that wrongly hung ~4227 on this XAU short)
    assert xau["stop_price"] == pytest.approx(4004.27 + 15.16 * 3.30, rel=0.001)
    assert xau["stop_price"] < 4100


def test_xau_short_r3_live_regression():
    """2026-07-17 XAU SHORT: ATR hard SL ≈4054, not entry% 4226.91."""
    meta = compute_vps_hard_sl(
        4004.27, "SHORT", atr=15.1599927843, regime=3,
        tv_sl_reference=4020.6159920628,
    )
    assert meta["stop_price"] == pytest.approx(4004.27 + 15.1599927843 * 3.30, abs=0.05)
    assert meta["tv_sl_reference"] == pytest.approx(4020.62, abs=0.02)
    assert meta["stop_price"] != pytest.approx(4226.91, abs=1.0)


def test_fallback_without_atr_uses_entry_pct_equiv():
    meta = compute_vps_hard_sl(1800.0, "LONG", atr=0.0, regime=3)
    assert meta["stop_price"] > 0
    assert meta["sl_distance"] == pytest.approx(1800.0 * hard_sl_pct(3), rel=0.01)


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
    # Hung price from ATR, not TV
    assert meta["stop_price"] == pytest.approx(2000.0 - 30.0 * 3.30, rel=0.001)
