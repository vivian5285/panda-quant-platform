"""Per-symbol REST pacing — whitepaper v3 §8.3 (≥100ms)."""

import time

from app.core.rest_symbol_pace import MIN_GAP_SEC, reset_for_tests, wait_turn


def test_min_gap_constant():
    assert abs(MIN_GAP_SEC - 0.100) < 1e-9


def test_wait_turn_enforces_gap():
    reset_for_tests()
    wait_turn(exchange="binance", user_id=6, symbol="ETHUSDT")
    t0 = time.monotonic()
    wait_turn(exchange="binance", user_id=6, symbol="ETHUSDT")
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.08  # allow timer jitter under 100ms target
    # Different symbol does not share the same gate key
    t1 = time.monotonic()
    wait_turn(exchange="binance", user_id=6, symbol="XAUUSDT")
    assert time.monotonic() - t1 < 0.05
