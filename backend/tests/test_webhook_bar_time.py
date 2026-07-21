"""Optional bar_time freshness gate."""

from app.services.webhook_bar_time import (
    check_and_accept_bar_time,
    coerce_bar_time_ms,
    note_bar_time_watermark,
    reset_bar_time_gate_for_tests,
)


def setup_function():
    reset_bar_time_gate_for_tests()


def test_coerce_seconds_to_ms():
    assert coerce_bar_time_ms(1_721_520_000) == 1_721_520_000_000
    assert coerce_bar_time_ms(1_721_520_000_000) == 1_721_520_000_000


def test_stale_bar_time_rejected():
    ok, reason, _ = check_and_accept_bar_time(symbol="ETHUSDT", bar_time=1_721_520_000_000)
    assert ok and reason == "accepted"
    ok2, reason2, meta = check_and_accept_bar_time(symbol="ETHUSDT", bar_time=1_721_510_000_000)
    assert not ok2 and reason2 == "stale_bar_time"
    assert meta["last_bar_time"] == 1_721_520_000_000


def test_missing_bar_time_passthrough():
    ok, reason, _ = check_and_accept_bar_time(symbol="ETHUSDT", bar_time=None)
    assert ok and reason == "no_bar_time"


def test_close_watermark_note_does_not_reject_path():
    check_and_accept_bar_time(symbol="ETHUSDT", bar_time=1_721_520_000_000)
    note_bar_time_watermark(symbol="ETHUSDT", bar_time=1_721_510_000_000)  # older — no-op down
    ok, _, meta = check_and_accept_bar_time(symbol="ETHUSDT", bar_time=1_721_520_000_000)
    assert ok
    assert meta["last_bar_time"] == 1_721_520_000_000
