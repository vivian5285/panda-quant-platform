"""Tests for safe recovery_context nested access."""

from app.core.startup_reconcile import recovery_section, apply_tv_sl_from_sources


def test_recovery_section_null_trade():
    ctx = {"trade": None, "open_log": {"qty": 1.0}}
    assert recovery_section(ctx, "trade") == {}
    assert recovery_section(ctx, "open_log")["qty"] == 1.0


def test_apply_tv_sl_prefers_latest_tv():
    class Target:
        tv_sl = 0.0

    t = Target()
    sl = apply_tv_sl_from_sources(
        t,
        {"tv_sl": 3550.0},
        {"tv_sl": 3400.0},
    )
    assert sl == 3550.0
    assert t.tv_sl == 3550.0
