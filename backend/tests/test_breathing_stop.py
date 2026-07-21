"""Breathing stop unit tests — user demo path + symmetry."""

from app.core.breathing_stop import (
    BREAKEVEN_TRIGGER_ATR,
    DEFAULT_ADX,
    INITIAL_SL_ATR,
    apply_breathing_tick,
    calculate_stop_long,
    calculate_stop_short,
    compute_initial_stop,
    init_breathing_state,
    stop_hit,
    trail_distance_by_adx,
)


def test_trail_distance_adx_bounds():
    assert trail_distance_by_adx(10) == 1.2
    assert trail_distance_by_adx(15) == 1.2
    assert trail_distance_by_adx(35) == 2.5
    assert trail_distance_by_adx(50) == 2.5
    mid = trail_distance_by_adx(25)
    assert abs(mid - 1.85) < 1e-9


def test_initial_stop_long_short():
    assert compute_initial_stop(1800, "LONG", 40) == 1740
    assert compute_initial_stop(1800, "SHORT", 40) == 1860


def test_init_state():
    st = init_breathing_state(1800, "LONG", atr=40, adx=20)
    assert st["initial_atr"] == 40
    assert st["initial_stop"] == 1740
    assert st["current_sl"] == 1740
    assert st["breakeven_phase"] is False
    assert st["current_adx"] == 20
    assert st["remaining_qty_pct"] == 1.0


def test_demo_path_long_1800_atr40():
    """User example: ETH 1800 ATR=40 LONG."""
    entry = 1800.0
    atr = 40.0
    initial_stop = entry - INITIAL_SL_ATR * atr
    current_stop = initial_stop
    highest = entry
    phase = False

    price_path = [1800, 1830, 1860, 1890, 1920, 1950, 1980, 2010, 2040, 2000, 2100]
    adx_path = [20, 20, 22, 24, 26, 28, 30, 32, 34, 30, 36]
    stops = []

    for price, adx in zip(price_path, adx_path):
        current_stop, highest, phase, meta = calculate_stop_long(
            price, entry, atr, initial_stop, current_stop, highest, phase, adx,
        )
        stops.append(current_stop)
        # Never retreat
        if len(stops) >= 2:
            assert current_stop >= stops[-2] - 1e-9

    # Open: still at initial
    assert abs(stops[0] - 1740) < 0.05
    # After +30 (~1 step): 1740 + 0.4*40 = 1756
    assert abs(stops[1] - 1756) < 0.05
    # Phase2 must engage by price=1920 (= entry+3ATR)
    # Recompute with fresh path to find first phase2
    current_stop = initial_stop
    highest = entry
    phase = False
    phase2_at = None
    for price, adx in zip(price_path, adx_path):
        current_stop, highest, phase, meta = calculate_stop_long(
            price, entry, atr, initial_stop, current_stop, highest, phase, adx,
        )
        if phase and phase2_at is None:
            phase2_at = price
            assert meta["event"] == "phase2_enter"
    assert phase2_at == 1920
    assert phase is True
    # Final stop only ratchets up; after peak 2100 trail is peak - dist*ATR
    assert current_stop > 1740
    assert highest == 2100


def test_apply_breathing_tick_wrapper():
    st = init_breathing_state(1800, "LONG", 40, 20)
    out = apply_breathing_tick(
        side="LONG",
        price=1830,
        entry_price=st["entry_price"],
        initial_atr=st["initial_atr"],
        initial_stop=st["initial_stop"],
        current_stop=st["current_sl"],
        best_price=st["best_price"],
        breakeven_phase=False,
        adx_val=20,
    )
    assert out["improved"] is True
    assert abs(out["current_sl"] - 1756) < 0.05
    assert out["event"] == "step"


def test_short_symmetric_no_retreat():
    entry = 1800.0
    atr = 40.0
    initial_stop = entry + INITIAL_SL_ATR * atr  # 1860
    current_stop = initial_stop
    lowest = entry
    phase = False
    prev = current_stop
    for price, adx in [(1800, 20), (1770, 20), (1740, 22), (1710, 24), (1680, 28)]:
        current_stop, lowest, phase, _ = calculate_stop_short(
            price, entry, atr, initial_stop, current_stop, lowest, phase, adx,
        )
        assert current_stop <= prev + 1e-9
        prev = current_stop
    assert phase is True  # 1800-3*40=1680
    assert current_stop < 1860


def test_stop_hit():
    assert stop_hit("LONG", 1739, 1740) is True
    assert stop_hit("LONG", 1741, 1740) is False
    assert stop_hit("SHORT", 1861, 1860) is True
    assert stop_hit("SHORT", 1859, 1860) is False


def test_default_adx_when_missing():
    st = init_breathing_state(1800, "LONG", 40, None)
    assert st["current_adx"] == DEFAULT_ADX


def test_breakeven_trigger_constant():
    assert BREAKEVEN_TRIGGER_ATR == 3.0


def test_recover_tick_never_retreats_long():
    """Restart recover: apply_breathing_tick must not lower an already-raised stop."""
    entry = 1800.0
    atr = 40.0
    initial_stop = 1740.0
    raised = 1756.0  # already stepped once
    out = apply_breathing_tick(
        side="LONG",
        price=1820,
        entry_price=entry,
        initial_atr=atr,
        initial_stop=initial_stop,
        current_stop=raised,
        best_price=1830,
        breakeven_phase=False,
        adx_val=20,
    )
    assert out["current_sl"] >= raised - 1e-9
