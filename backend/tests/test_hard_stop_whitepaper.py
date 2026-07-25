"""Whitepaper three-layer defense: hard permanence + formula (v3.0)."""

from app.core.breathing_stop import compute_temp_tv_stop, TEMP_TV_STOP_BUFFER


def test_hard_formula_long_example():
    # 1900 entry, TV SL 1880 → dist 20×1.15=23 → hard 1877
    assert TEMP_TV_STOP_BUFFER == 1.15
    assert compute_temp_tv_stop(1900, "LONG", 1880) == 1877.0


def test_hard_formula_short():
    # dist 20×1.15=23 → hard 1923
    assert compute_temp_tv_stop(1900, "SHORT", 1920) == 1923.0


def test_hard_requires_tv_stop_loss():
    assert compute_temp_tv_stop(1900, "LONG", 0) == 0.0
    assert compute_temp_tv_stop(1900, "LONG", None) == 0.0


def test_whitepaper_v3_worked_example():
    # TV 1900 / SL 1874 → dist 26 ×1.15=29.90; fill 1900.80 → 1870.90
    assert abs(
        compute_temp_tv_stop(1900.80, "LONG", 1874.0, tv_entry=1900.0) - 1870.90
    ) < 1e-6
