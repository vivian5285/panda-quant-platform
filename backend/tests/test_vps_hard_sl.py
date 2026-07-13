"""VPS autonomous hard stop — v6.9.103 breathing space spec."""

import pytest

from app.core.vps_hard_sl import (
    compute_hard_sl_distance,
    compute_vps_hard_sl,
    hard_sl_final_multiplier,
)


def test_regime4_breathing_space_at_reference_atr():
    dist = compute_hard_sl_distance(16.65, 4)
    assert dist == pytest.approx(99.9, rel=0.01)
    assert hard_sl_final_multiplier(4) == pytest.approx(6.0)


def test_regime2_example_from_spec():
    meta = compute_vps_hard_sl(1819.0, "LONG", 16.65, 2)
    assert meta["sl_distance"] == pytest.approx(31.47, rel=0.02)
    assert meta["stop_price"] == pytest.approx(1787.53, rel=0.01)
    assert meta["source"] == "vps_computed"


def test_all_regimes_monotonic_distance():
    atr = 16.65
    dists = [compute_hard_sl_distance(atr, r) for r in (1, 2, 3, 4)]
    assert dists == sorted(dists)
    assert dists[0] == pytest.approx(14.99, rel=0.02)
    assert dists[3] == pytest.approx(99.9, rel=0.01)


def test_short_stop_above_entry():
    meta = compute_vps_hard_sl(1819.0, "SHORT", 16.65, 2)
    assert meta["stop_price"] > 1819.0
