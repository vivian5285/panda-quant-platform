"""Continuous trailDistanceMultiplier + initial_atr lock tests."""

from app.core.breathing_profile import (
    ETH_PROFILE,
    XAU_PROFILE,
    cold_start_multiplier,
    trail_distance_multiplier,
)
from app.core.breathing_stop import (
    get_breathing_coefficient,
    init_breathing_state,
    load_breathing_coef,
    resolve_breathing_coef,
)
from app.core.atr_1h_breathing import update_breathing_coefficient
from app.core.initial_atr_lock import (
    InitialAtrDescriptor,
    blocked_initial_atr_writes,
    is_initial_atr_locked,
)


def test_continuous_ends_and_midpoints():
    # Floor / ceiling
    assert abs(trail_distance_multiplier(0.5, ETH_PROFILE) - 1.2) < 1e-9
    assert abs(trail_distance_multiplier(2.5, ETH_PROFILE) - 2.5) < 1e-9
    assert abs(trail_distance_multiplier(0.5, XAU_PROFILE) - 0.5) < 1e-9
    assert abs(trail_distance_multiplier(2.5, XAU_PROFILE) - 1.2) < 1e-9
    # Cold start ratio=1.0 → min + (max-min)*0.25
    assert abs(cold_start_multiplier(ETH_PROFILE) - 1.525) < 1e-9
    assert abs(cold_start_multiplier(XAU_PROFILE) - 0.675) < 1e-9
    assert abs(get_breathing_coefficient(1.0, "ETHUSDT") - 1.525) < 1e-9
    assert abs(get_breathing_coefficient(1.0, "XAUUSDT") - 0.675) < 1e-9
    # Midpoints continuous (no discrete jump)
    eth_07 = get_breathing_coefficient(0.7, "ETHUSDT")
    eth_10 = get_breathing_coefficient(1.0, "ETHUSDT")
    eth_14 = get_breathing_coefficient(1.4, "ETHUSDT")
    assert eth_07 < eth_10 < eth_14
    xau_07 = get_breathing_coefficient(0.7, "XAUUSDT")
    xau_10 = get_breathing_coefficient(1.0, "XAUUSDT")
    assert xau_07 < xau_10
    # XAU always tighter than ETH at same ratio
    for r in (0.6, 1.0, 1.4, 2.0, 2.2):
        assert get_breathing_coefficient(r, "XAUUSDT") <= get_breathing_coefficient(r, "ETHUSDT")


def test_missing_coef_seed_is_cold_start_not_literal_one():
    """Idle/missing seed must not use literal 1.0 (clamps ETH→1.2, leaves XAU too loose)."""
    assert abs(resolve_breathing_coef(None, "ETHUSDT") - 1.525) < 1e-9
    assert abs(resolve_breathing_coef(None, "XAUUSDT") - 0.675) < 1e-9
    assert abs(load_breathing_coef(None, "ETHUSDT") - 1.525) < 1e-9
    assert abs(load_breathing_coef(0, "XAUUSDT") - 0.675) < 1e-9
    assert abs(load_breathing_coef(0.744, "XAUUSDT") - 0.744) < 1e-9
    # Literal 1.0 is a real in-range value for XAU — keep as-is when persisted from live
    assert abs(resolve_breathing_coef(1.0, "XAUUSDT") - 1.0) < 1e-9
    # ETH 1.0 is below minMult → clamp to 1.2 (why idle must store cold 1.525, not 1.0)
    assert abs(resolve_breathing_coef(1.0, "ETHUSDT") - 1.2) < 1e-9


def test_smooth_then_interpolate():
    coef, hist, smooth = update_breathing_coefficient(
        initial_atr=20.0, atr_1h=13.0, ratio_history=[], symbol="ETHUSDT",
    )
    assert abs(hist[-1] - 0.65) < 1e-9
    # ratio 0.65 → near floor → ~1.2 + small
    assert abs(coef - get_breathing_coefficient(0.65, "ETHUSDT")) < 1e-9
    coef, hist, smooth = update_breathing_coefficient(
        initial_atr=20.0, atr_1h=20.0, ratio_history=hist, symbol="ETHUSDT",
    )
    coef, hist, smooth = update_breathing_coefficient(
        initial_atr=20.0, atr_1h=26.0, ratio_history=hist, symbol="ETHUSDT",
    )
    assert len(hist) == 3
    assert abs(smooth - (0.65 + 1.0 + 1.3) / 3) < 1e-9
    assert abs(coef - get_breathing_coefficient(smooth, "ETHUSDT")) < 1e-9


def test_init_state_uses_cold_start_coef():
    st = init_breathing_state(1800, "LONG", atr=40)
    assert abs(st["breathing_coefficient"] - 1.525) < 1e-9


def test_initial_atr_lock_blocks_overwrite():
    class _S:
        initial_atr = InitialAtrDescriptor()
        user_id = 99

    s = _S()
    s.initial_atr = 14.5
    assert s.initial_atr == 14.5
    assert is_initial_atr_locked(s)
    s.initial_atr = 99.0  # blocked
    assert s.initial_atr == 14.5
    assert blocked_initial_atr_writes(s) == 1
    s.initial_atr = 14.5  # same ok
    assert s.initial_atr == 14.5
    s.initial_atr = 0  # flat clear
    assert s.initial_atr == 0.0
    assert not is_initial_atr_locked(s)
    s.initial_atr = 8.0
    assert s.initial_atr == 8.0
