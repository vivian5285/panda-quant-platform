"""Hard-stop buffer pad + slip + radar floor (Part 1 whitepaper fix)."""

from app.core.breathing_profile import radar_arm_distance, radar_start_ratio
from app.core.breathing_stop import (
    HARD_SLIP_MULT,
    HARD_VS_RADAR_FLOOR,
    TEMP_TV_STOP_BUFFER,
    compute_hard_stop_distance,
    compute_temp_tv_stop,
)


def test_legacy_example_without_atr_still_1876():
    assert TEMP_TV_STOP_BUFFER == 1.2
    assert compute_temp_tv_stop(1900, "LONG", 1880) == 1876.0
    assert compute_temp_tv_stop(1900, "SHORT", 1920) == 1924.0


def test_hard_uses_tv_entry_for_implied_not_fill():
    # TV entry 1900 / SL 1880 → implied 24; fill slipped to 1905
    # base=24, slip=|1905-1900|*2=10 → dist=34 → hard=1871
    hard = compute_temp_tv_stop(
        1905, "LONG", 1880, tv_entry=1900, initial_atr=None,
    )
    assert abs(hard - 1871.0) < 1e-9


def test_hard_radar_floor_beats_tight_tv_sl():
    fill, tv_e, tv_sl, atr = 1900.0, 1900.0, 1895.0, 20.0
    # TV implied = 5*1.2=6; radar floor = 1.5*20*1.05=31.5 → base=31.5
    meta = compute_hard_stop_distance(
        fill_entry=fill, tv_stop_loss=tv_sl, tv_entry=tv_e, initial_atr=atr,
        symbol="ETHUSDT",
    )
    assert abs(meta["radar_floor_dist"] - 1.5 * atr * HARD_VS_RADAR_FLOOR) < 1e-9
    assert meta["base_dist"] >= meta["radar_floor_dist"] - 1e-12
    hard = compute_temp_tv_stop(
        fill, "LONG", tv_sl, tv_entry=tv_e, initial_atr=atr, symbol="ETHUSDT",
    )
    radar_init = fill - 1.5 * atr
    assert hard < radar_init - 1e-9  # farther from entry than radar
    assert abs(hard - (fill - meta["final_dist"])) < 1e-9


def test_slip_mult_default_is_2():
    assert HARD_SLIP_MULT == 2.0
    meta = compute_hard_stop_distance(
        fill_entry=1910, tv_stop_loss=1880, tv_entry=1900,
    )
    assert abs(meta["slip_dist"] - 20.0) < 1e-9


def test_radar_arm_inverse_of_vol_ratio():
    # Calm (ratio at floor) → late arm 85%; volatile (ceiling) → early 50%
    assert abs(radar_start_ratio(0.6) - 0.85) < 1e-9
    assert abs(radar_start_ratio(2.2) - 0.50) < 1e-9
    atr = 10.0
    # Cold-start ratio 1.0 → between 50 and 85
    arm = radar_arm_distance(atr, 1.0)
    assert 1.35 * atr * 0.50 - 1e-9 <= arm <= 1.35 * atr * 0.85 + 1e-9
    assert arm > 0.75 * atr  # later than old fixed 0.75 at calm-ish mid
