"""VPS autonomous hard stop — 四档均匀递增 breathing space."""

import pytest

from app.core.vps_hard_sl import (
    HARD_SL_STOP_LIMIT_OFFSET,
    compute_hard_sl_distance,
    compute_hard_sl_limit_price,
    compute_vps_hard_sl,
    hard_sl_final_multiplier,
)


def test_regime4_breathing_space_at_reference_atr():
    dist = compute_hard_sl_distance(16.0, 4)
    assert dist == pytest.approx(100.0, rel=0.01)
    assert hard_sl_final_multiplier(4) == pytest.approx(6.25)


def test_regime_multipliers_uniform_increase():
    assert hard_sl_final_multiplier(1) == pytest.approx(1.80)
    assert hard_sl_final_multiplier(2) == pytest.approx(3.15)
    assert hard_sl_final_multiplier(3) == pytest.approx(4.40)
    assert hard_sl_final_multiplier(4) == pytest.approx(6.25)


def test_regime2_long_example():
    meta = compute_vps_hard_sl(1819.0, "LONG", 16.65, 2)
    assert meta["sl_distance"] == pytest.approx(52.45, rel=0.02)
    assert meta["stop_price"] == pytest.approx(1766.55, rel=0.01)
    assert meta["source"] == "vps_computed"


def test_short_example_from_spec():
    """ATR=15.78, R1 short @ 1777.33 → stop ≈ 1805.73."""
    meta = compute_vps_hard_sl(1777.33, "SHORT", 15.78, 1)
    assert meta["sl_distance"] == pytest.approx(28.4, rel=0.02)
    assert meta["stop_price"] == pytest.approx(1805.73, rel=0.01)


def test_all_regimes_monotonic_distance():
    atr = 16.0
    dists = [compute_hard_sl_distance(atr, r) for r in (1, 2, 3, 4)]
    assert dists == sorted(dists)
    assert dists[0] == pytest.approx(28.8, rel=0.02)
    assert dists[3] == pytest.approx(100.0, rel=0.01)


def test_stop_limit_offset_long():
    assert compute_hard_sl_limit_price(1800.0, "LONG") == pytest.approx(
        1800.0 - HARD_SL_STOP_LIMIT_OFFSET, rel=0.001,
    )


def test_stop_limit_offset_short():
    assert compute_hard_sl_limit_price(1805.73, "SHORT") == pytest.approx(
        1805.73 + HARD_SL_STOP_LIMIT_OFFSET, rel=0.001,
    )


def test_short_stop_above_entry():
    meta = compute_vps_hard_sl(1819.0, "SHORT", 16.65, 2)
    assert meta["stop_price"] > 1819.0
    assert meta["limit_price"] > meta["stop_price"]
