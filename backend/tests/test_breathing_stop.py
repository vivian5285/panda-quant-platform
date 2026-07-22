"""Breathing stop unit tests — ETH defaults + XAU profile isolation."""

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


def test_breathing_coefficient_ladder_eth():
    assert get_breathing_coefficient(0.5) == 0.7
    assert get_breathing_coefficient(0.8) == 0.85
    assert get_breathing_coefficient(1.2) == 1.0
    assert abs(get_breathing_coefficient(1.75) - 1.3166666667) < 1e-6
    assert get_breathing_coefficient(2.5) == 1.5


def test_breathing_coefficient_ladder_xau_tighter():
    assert get_breathing_coefficient(0.5, "XAUUSDT") == 0.5
    assert get_breathing_coefficient(0.8, "XAUUSDT") == 0.7
    assert get_breathing_coefficient(1.2, "XAUUSDT") == 0.9
    assert abs(get_breathing_coefficient(1.75, "XAUUSDT") - 1.1166666667) < 1e-6
    assert get_breathing_coefficient(2.5, "XAUUSDT") == 1.3
    # XAU always ≤ ETH at same ratio
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
    entry, atr, coef = 3300.0, 10.0, 1.0
    initial_stop = compute_initial_stop(entry, "LONG", atr, symbol="XAUUSDT")
    assert abs(initial_stop - (entry - 1.5 * atr)) < 1e-9
    # Before early BE (0.3×ATR=3): +2 pts → 0 steps
    stop, high, phase, meta = calculate_stop_long(
        entry + 2, entry, atr, initial_stop, initial_stop, entry, False, coef,
        symbol="XAUUSDT",
    )
    assert meta["event"] == "none"
    assert abs(stop - initial_stop) < 1e-9
    # Early BE at +0.3×ATR
    stop, high, phase, meta = calculate_stop_long(
        entry + 3.0, entry, atr, initial_stop, initial_stop, entry, False, coef,
        symbol="XAUUSDT",
    )
    assert meta["event"] == "early_breakeven"
    assert abs(stop - (entry + 0.01)) < 1e-6
    # Step at 0.4×ATR=4: with coef=1, after early BE already above step stop
    stop2, _, _, meta2 = calculate_stop_long(
        entry + 4.0, entry, atr, initial_stop, stop, high, False, coef,
        symbol="XAUUSDT",
    )
    assert meta2["step_count"] == 1
    assert stop2 >= stop - 1e-9


def test_init_state():
    st = init_breathing_state(1800, "LONG", atr=40, breathing_coefficient=1.0)
    assert st["initial_atr"] == 40
    assert st["initial_stop"] == 1740
    assert st["current_sl"] == 1740
    assert st["breakeven_phase"] is False
    assert st["breathing_coefficient"] == 1.0
    assert st["remaining_qty_pct"] == 1.0
    assert st["symbol_tag"] == "ETH"

    st_x = init_breathing_state(
        3300, "LONG", atr=10, breathing_coefficient=1.0, symbol="XAUUSDT",
    )
    assert st_x["symbol_tag"] == "XAU"
    assert abs(st_x["initial_stop"] - 3285.0) < 1e-9


def test_demo_path_long_1800_atr40_coef1():
    """ETH 1800 ATR=40 LONG, breath=1.0 — early BE at +0.5×ATR."""
    entry = 1800.0
    atr = 40.0
    coef = 1.0
    initial_stop = entry - INITIAL_SL_ATR * atr
    current_stop = initial_stop
    highest = entry
    phase = False

    price_path = [1800, 1830, 1860, 1890, 1920, 1950, 1980, 2010, 2040, 2000, 2100]
    stops = []

    for price in price_path:
        current_stop, highest, phase, meta = calculate_stop_long(
            price, entry, atr, initial_stop, current_stop, highest, phase, coef,
        )
        stops.append(current_stop)
        if len(stops) >= 2:
            assert current_stop >= stops[-2] - 1e-9

    assert abs(stops[0] - 1740) < 0.05
    # +30 (≥0.5×ATR early BE) → entry + 1 tick
    assert abs(stops[1] - (entry + 0.01)) < 0.05

    current_stop = initial_stop
    highest = entry
    phase = False
    phase2_at = None
    for price in price_path:
        current_stop, highest, phase, meta = calculate_stop_long(
            price, entry, atr, initial_stop, current_stop, highest, phase, coef,
        )
        if phase and phase2_at is None:
            phase2_at = price
            assert meta["event"] == "phase2_enter"
    assert phase2_at == entry + BREAKEVEN_TRIGGER_ATR * atr  # 1920


def test_phase2_trail_uses_breath_coef():
    entry, atr, coef = 1900.0, 20.0, 1.3
    initial_stop = compute_initial_stop(entry, "LONG", atr)
    stop, high, phase, meta = calculate_stop_long(
        2000, entry, atr, initial_stop, initial_stop, 2000, True, coef,
    )
    assert phase is True
    assert abs(meta["trail_distance"] - atr * coef) < 1e-9
    assert abs(stop - (2000 - atr * coef)) < 1e-9


def test_phase2_trail_xau_tighten_0_8():
    entry, atr, coef = 3300.0, 10.0, 1.0
    initial_stop = compute_initial_stop(entry, "LONG", atr, symbol="XAUUSDT")
    stop, high, phase, meta = calculate_stop_long(
        3400, entry, atr, initial_stop, initial_stop, 3400, True, coef,
        symbol="XAUUSDT",
    )
    assert phase is True
    assert abs(meta["trail_distance"] - atr * coef * 0.8) < 1e-9
    assert abs(stop - (3400 - atr * coef * 0.8)) < 1e-9


def test_apply_tick_and_hit():
    st = init_breathing_state(1900, "LONG", atr=20, breathing_coefficient=1.0)
    out = apply_breathing_tick(
        side="LONG",
        price=1910,
        entry_price=1900,
        initial_atr=20,
        initial_stop=st["initial_stop"],
        current_stop=st["current_sl"],
        best_price=1900,
        breakeven_phase=False,
        breathing_coefficient=1.0,
    )
    assert out["current_sl"] >= st["initial_stop"] - 1e-9
    assert not stop_hit("LONG", 1910, out["current_sl"])
    assert stop_hit("LONG", out["current_sl"] - 0.01, out["current_sl"])


def test_short_symmetric_step():
    entry, atr, coef = 1900.0, 20.0, 1.0
    initial_stop = compute_initial_stop(entry, "SHORT", atr)
    # Move 15 pts = 0.75 ATR → 1 step; also ≥0.5 ATR early BE → entry - tick wins
    stop, low, phase, meta = calculate_stop_short(
        1885, entry, atr, initial_stop, initial_stop, entry, False, coef,
    )
    assert meta["step_count"] == 1
    assert meta["event"] == "early_breakeven"
    assert abs(stop - (entry - 0.01)) < 1e-6
    assert phase is False
