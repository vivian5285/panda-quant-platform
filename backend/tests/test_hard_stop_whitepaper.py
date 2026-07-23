"""Whitepaper three-layer defense: hard permanence + formula."""

from app.core.breathing_stop import compute_temp_tv_stop, TEMP_TV_STOP_BUFFER


def test_hard_formula_long_example():
    # 1900 entry, TV SL 1880 → dist 20×1.2=24 → hard 1876
    assert TEMP_TV_STOP_BUFFER == 1.2
    assert compute_temp_tv_stop(1900, "LONG", 1880) == 1876.0


def test_hard_formula_short():
    assert compute_temp_tv_stop(1900, "SHORT", 1920) == 1924.0


def test_hard_requires_tv_stop_loss():
    assert compute_temp_tv_stop(1900, "LONG", 0) == 0.0
    assert compute_temp_tv_stop(1900, "LONG", None) == 0.0
