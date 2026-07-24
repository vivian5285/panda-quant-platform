"""Hard-stop = |TV.e−SL| × buffer from fill (no ATR floor / slip pad)."""

from app.core.breathing_profile import radar_arm_distance, radar_start_ratio
from app.core.breathing_stop import (
    HARD_SLIP_MULT,
    TEMP_TV_STOP_BUFFER,
    compute_hard_stop_distance,
    compute_temp_tv_stop,
)


def test_legacy_example_without_atr_still_1876():
    assert TEMP_TV_STOP_BUFFER == 1.2
    assert compute_temp_tv_stop(1900, "LONG", 1880) == 1876.0
    assert compute_temp_tv_stop(1900, "SHORT", 1920) == 1924.0


def test_hard_uses_tv_entry_for_implied_not_fill():
    # TV entry 1900 / SL 1880 → dist 20×1.2=24; fill slipped to 1905 → hard 1881
    hard = compute_temp_tv_stop(
        1905, "LONG", 1880, tv_entry=1900, initial_atr=None,
    )
    assert abs(hard - 1881.0) < 1e-9


def test_hard_ignores_atr_floor():
    fill, tv_e, tv_sl, atr = 1900.0, 1900.0, 1895.0, 20.0
    # TV implied = 5*1.2=6; ATR floor removed → base=6
    meta = compute_hard_stop_distance(
        fill_entry=fill, tv_stop_loss=tv_sl, tv_entry=tv_e, initial_atr=atr,
        symbol="ETHUSDT",
    )
    assert abs(meta["radar_floor_dist"]) < 1e-12
    assert abs(meta["base_dist"] - 6.0) < 1e-9
    hard = compute_temp_tv_stop(
        fill, "LONG", tv_sl, tv_entry=tv_e, initial_atr=atr, symbol="ETHUSDT",
    )
    assert abs(hard - (fill - 6.0)) < 1e-9


def test_slip_mult_default_is_zero():
    assert HARD_SLIP_MULT == 0.0
    meta = compute_hard_stop_distance(
        fill_entry=1910, tv_stop_loss=1880, tv_entry=1900,
    )
    assert abs(meta["slip_dist"]) < 1e-12
    assert abs(meta["final_dist"] - 24.0) < 1e-9


def test_reject_missing_or_tiny_tv_stop():
    miss = compute_hard_stop_distance(fill_entry=1900, tv_stop_loss=0, tv_entry=1900)
    assert miss["reject_reason"] == "missing_tv_stop_or_entry"
    tiny = compute_hard_stop_distance(
        fill_entry=1900, tv_stop_loss=1899.99, tv_entry=1900, symbol="ETHUSDT",
    )
    # ETH tick 0.01 → 5 ticks = 0.05; dist 0.01 → reject
    assert tiny["reject_reason"] == "tv_stop_distance_too_small"


def test_radar_arm_inverse_of_vol_ratio():
    assert abs(radar_start_ratio(0.6) - 0.85) < 1e-9
    assert abs(radar_start_ratio(2.2) - 0.50) < 1e-9
    atr = 10.0
    arm = radar_arm_distance(atr, 1.0)
    assert 1.35 * atr * 0.50 - 1e-9 <= arm <= 1.35 * atr * 0.85 + 1e-9
    assert arm > 0.75 * atr
