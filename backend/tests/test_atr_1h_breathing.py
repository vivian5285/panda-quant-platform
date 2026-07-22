"""Binance 1h ATR breathing coefficient engine tests."""

from app.core.atr_1h_breathing import (
    breathing_coefficient_from_ratio,
    compute_atr_1h_from_klines,
    reset_1h_atr_cache_for_tests,
    update_breathing_coefficient,
)
from app.core.breathing_stop import get_breathing_coefficient


def test_coefficient_alias_matches():
    for r in (0.5, 0.85, 1.2, 1.75, 2.5):
        assert breathing_coefficient_from_ratio(r) == get_breathing_coefficient(r)


def test_update_breathing_smooths_three_samples():
    coef, hist, smooth = update_breathing_coefficient(
        initial_atr=20.0, atr_1h=13.0, ratio_history=[],
    )
    assert abs(hist[-1] - 0.65) < 1e-9
    assert coef == 0.7

    coef, hist, smooth = update_breathing_coefficient(
        initial_atr=20.0, atr_1h=20.0, ratio_history=hist,
    )
    coef, hist, smooth = update_breathing_coefficient(
        initial_atr=20.0, atr_1h=26.0, ratio_history=hist,
    )
    assert len(hist) == 3
    assert abs(smooth - (0.65 + 1.0 + 1.3) / 3) < 1e-9
    # smooth ≈ 0.983 → still in 0.7~1.0 band → 0.85
    assert coef == 0.85


def test_compute_atr_1h_from_synthetic_klines():
    # Build enough 1h bars with TR≈10
    rows = []
    t0 = 1_700_000_000_000
    close = 100.0
    for i in range(40):
        o = close
        h = o + 10
        l = o - 0.1
        c = o + 5
        rows.append([t0 + i * 3_600_000, str(o), str(h), str(l), str(c), "1"])
        close = c
    atr = compute_atr_1h_from_klines(rows)
    assert atr > 0


def test_reset_cache():
    reset_1h_atr_cache_for_tests()
