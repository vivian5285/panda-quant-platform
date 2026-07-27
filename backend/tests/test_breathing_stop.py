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
    # Mid-tier whitepaper ETH coef 2.0~2.5
    assert abs(get_breathing_coefficient(0.5) - 2.0) < 1e-9
    # ratio 1.0 → t=(1-0.6)/(2.2-0.6)=0.25 → 2.0+0.25*0.5=2.125
    assert abs(get_breathing_coefficient(1.0) - 2.125) < 1e-9
    assert abs(get_breathing_coefficient(2.2) - 2.5) < 1e-9


def test_breathing_coefficient_continuous_xau_mid_tier():
    # Mid-tier XAU coef 1.8~2.2
    assert abs(get_breathing_coefficient(0.5, "XAUUSDT") - 1.8) < 1e-9
    assert abs(get_breathing_coefficient(2.2, "XAUUSDT") - 2.2) < 1e-9


def test_initial_stop_and_buffer_eth_default():
    assert compute_initial_stop(1800, "LONG", 40) == 1740
    assert compute_initial_stop(1800, "SHORT", 40) == 1860
    assert apply_stop_order_buffer("LONG", 1740) == 1740 - STOP_ORDER_BUFFER_USDT
    assert apply_stop_order_buffer("SHORT", 1860) == 1860 + STOP_ORDER_BUFFER_USDT


def test_xau_radar_waits_then_activates():
    assert apply_stop_order_buffer("LONG", 3300, "XAUUSDT") == 3299.5
    assert apply_stop_order_buffer("SHORT", 3300, "XAUUSDT") == 3300.5
    entry, atr = 3300.0, 10.0
    coef = 1.9
    initial_stop = compute_initial_stop(entry, "LONG", atr, symbol="XAUUSDT")
    assert abs(initial_stop - (entry - 1.5 * atr)) < 1e-9
    # ADX=17 → 70% × 1.35×ATR
    arm_px = entry + 1.35 * atr * 0.70
    stop, high, phase, meta = calculate_stop_long(
        entry + 2, entry, atr, initial_stop, initial_stop, entry, False, coef,
        symbol="XAUUSDT", smooth_ratio=1.0, adx=17.0, radar_activated=False,
        step_trigger_atr=0.40, early_breakeven_atr=0.5, step_advance_atr=0.30,
        breath_tp1_tp2_atr=1.0,
    )
    assert meta["event"] == "waiting_arm"
    assert abs(stop - initial_stop) < 1e-9
    stop, high, phase, meta = calculate_stop_long(
        arm_px, entry, atr, initial_stop, initial_stop, entry, False, coef,
        symbol="XAUUSDT", smooth_ratio=1.0, adx=17.0, radar_activated=False,
        step_trigger_atr=0.40, early_breakeven_atr=0.5, step_advance_atr=0.30,
        breath_tp1_tp2_atr=1.0,
    )
    assert meta.get("just_activated") or meta["event"] == "radar_activate"
    assert meta.get("radar_arm_mode") == "adx_70_90"
    assert stop >= entry + 0.5 * atr - 1e-9


def test_init_state():
    st = init_breathing_state(1800, "LONG", atr=40)
    assert st["initial_atr"] == 40
    assert st["initial_stop"] == 1740
    assert st["current_sl"] == 1740
    assert st["breakeven_phase"] is False
    # Cold-start coef = mid-tier ETH at ratio 1.0 → 2.125
    assert abs(st["breathing_coefficient"] - 2.125) < 1e-9
    assert st["remaining_qty_pct"] == 1.0
