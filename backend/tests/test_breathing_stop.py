"""Breathing stop unit tests — continuous coef + XAU profile isolation."""

from app.core.breathing_stop import (
    BREAKEVEN_TRIGGER_ATR,
    INITIAL_SL_ATR,
    STOP_ORDER_BUFFER_USDT,
    apply_breathing_tick,
    apply_stop_order_buffer,
    calculate_stop_long,
    calculate_stop_short,
    compute_initial_stop,
    get_breathing_coefficient,
    init_breathing_state,
    stop_hit,
)


def test_breathing_coefficient_continuous_eth():
    assert abs(get_breathing_coefficient(0.5) - 1.2) < 1e-9
    assert abs(get_breathing_coefficient(1.0) - 1.525) < 1e-9
    assert abs(get_breathing_coefficient(2.2) - 2.5) < 1e-9
    # Linear mid: ratio 1.4 → 1.2 + 1.3*(0.8/1.6)=1.85
    assert abs(get_breathing_coefficient(1.4) - 1.85) < 1e-9


def test_breathing_coefficient_continuous_xau_tighter():
    assert abs(get_breathing_coefficient(0.5, "XAUUSDT") - 0.5) < 1e-9
    assert abs(get_breathing_coefficient(1.0, "XAUUSDT") - 0.675) < 1e-9
    assert abs(get_breathing_coefficient(2.2, "XAUUSDT") - 1.2) < 1e-9
    for r in (0.5, 0.8, 1.2, 1.75, 2.5):
        assert get_breathing_coefficient(r, "XAUUSDT") <= get_breathing_coefficient(r, "ETHUSDT")


def test_initial_stop_and_buffer_eth_default():
    assert compute_initial_stop(1800, "LONG", 40) == 1740
    assert compute_initial_stop(1800, "SHORT", 40) == 1860
    assert apply_stop_order_buffer("LONG", 1740) == 1740 - STOP_ORDER_BUFFER_USDT
    assert apply_stop_order_buffer("SHORT", 1860) == 1860 + STOP_ORDER_BUFFER_USDT


def test_xau_buffer_and_steps():
    assert apply_stop_order_buffer("LONG", 3300, "XAUUSDT") == 3299.5
    assert apply_stop_order_buffer("SHORT", 3300, "XAUUSDT") == 3300.5
    entry, atr = 3300.0, 10.0
    coef = 0.675  # cold-start-ish; phase1 steps ignore coef
    initial_stop = compute_initial_stop(entry, "LONG", atr, symbol="XAUUSDT")
    assert abs(initial_stop - (entry - 1.5 * atr)) < 1e-9
    # Dynamic arm at cold ratio≈1.0 ≈ TP1×~0.76 ≈ 10.3; move 2 < arm → no step
    stop, high, phase, meta = calculate_stop_long(
        entry + 2, entry, atr, initial_stop, initial_stop, entry, False, coef,
        symbol="XAUUSDT", smooth_ratio=1.0,
    )
    assert meta["event"] == "none"
    assert abs(stop - initial_stop) < 1e-9
    stop, high, phase, meta = calculate_stop_long(
        entry + 3.0, entry, atr, initial_stop, initial_stop, entry, False, coef,
        symbol="XAUUSDT", smooth_ratio=1.0,
    )
    assert meta["event"] == "early_breakeven"
    assert abs(stop - (entry + 0.01)) < 1e-6
    # First radar step only after arm distance (~10.3)
    arm = float(meta.get("radar_arm_dist") or 0)
    assert arm > 8.0
    stop2, high2, _, meta2 = calculate_stop_long(
        entry + arm + 0.01, entry, atr, initial_stop, stop, high, False, coef,
        symbol="XAUUSDT", smooth_ratio=1.0,
    )
    assert meta2["step_count"] >= 1
    assert stop2 >= stop - 1e-9


def test_init_state():
    st = init_breathing_state(1800, "LONG", atr=40)
    assert st["initial_atr"] == 40
    assert st["initial_stop"] == 1740
    assert st["current_sl"] == 1740
    assert st["breakeven_phase"] is False
    assert abs(st["breathing_coefficient"] - 1.525) < 1e-9
    assert st["remaining_qty_pct"] == 1.0
