"""Breathing stop unit tests — adaptive breath coef path."""

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


def test_breathing_coefficient_ladder():
    assert get_breathing_coefficient(0.5) == 0.7
    assert get_breathing_coefficient(0.8) == 0.85
    assert get_breathing_coefficient(1.2) == 1.0
    assert abs(get_breathing_coefficient(1.75) - 1.3166666667) < 1e-6
    assert get_breathing_coefficient(2.5) == 1.5


def test_initial_stop_and_buffer():
    assert compute_initial_stop(1800, "LONG", 40) == 1740
    assert compute_initial_stop(1800, "SHORT", 40) == 1860
    assert apply_stop_order_buffer("LONG", 1740) == 1740 - STOP_ORDER_BUFFER_USDT
    assert apply_stop_order_buffer("SHORT", 1860) == 1860 + STOP_ORDER_BUFFER_USDT


def test_init_state():
    st = init_breathing_state(1800, "LONG", atr=40, breathing_coefficient=1.0)
    assert st["initial_atr"] == 40
    assert st["initial_stop"] == 1740
    assert st["current_sl"] == 1740
    assert st["breakeven_phase"] is False
    assert st["breathing_coefficient"] == 1.0
    assert st["remaining_qty_pct"] == 1.0


def test_demo_path_long_1800_atr40_coef1():
    """User example: ETH 1800 ATR=40 LONG, breath=1.0."""
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
    # +30 → 1 step: 1740 + 0.4*40 = 1756
    assert abs(stops[1] - 1756) < 0.05

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
    # Already in phase2
    stop, high, phase, meta = calculate_stop_long(
        2000, entry, atr, initial_stop, initial_stop, 2000, True, coef,
    )
    assert phase is True
    assert abs(meta["trail_distance"] - atr * coef) < 1e-9
    assert abs(stop - (2000 - atr * coef)) < 1e-9


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
    # Small move: 15 pts → 1 step, before TP1 floor (1.35×ATR=27)
    stop, low, phase, meta = calculate_stop_short(
        1885, entry, atr, initial_stop, initial_stop, entry, False, coef,
    )
    assert meta["step_count"] == 1
    assert abs(stop - (initial_stop - 1 * 0.4 * atr)) < 1e-9
    assert phase is False
