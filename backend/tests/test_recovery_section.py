"""Tests for safe recovery_context nested access."""

from app.core.startup_reconcile import recovery_section, apply_tv_sl_from_sources, adopt_live_tv_side


def test_recovery_section_null_trade():
    ctx = {"trade": None, "open_log": {"qty": 1.0}}
    assert recovery_section(ctx, "trade") == {}
    assert recovery_section(ctx, "open_log")["qty"] == 1.0


def test_adopt_live_tv_side_trusts_manual_long():
    class Sup:
        last_tv_side = "SHORT"
        current_side = "LONG"

    sup = Sup()
    result = adopt_live_tv_side(
        sup,
        {"latest_tv_action": "LONG"},
        adopted_manual=True,
    )
    assert sup.last_tv_side == "LONG"
    assert result["realigned"] is True
    assert result["reason"] == "trust_live_manual"
    assert result["force_close"] is False


def test_adopt_live_tv_side_opposite_marks_force_close():
    class Sup:
        last_tv_side = "SHORT"
        current_side = "LONG"

    sup = Sup()
    result = adopt_live_tv_side(sup, {"latest_tv_action": "SHORT"})
    assert result["force_close"] is True
    assert result["conflict"] is True
    assert sup.last_tv_side == "SHORT"


def test_adopt_live_tv_side_manual_opposite_still_force_close():
    class Sup:
        last_tv_side = "LONG"
        current_side = "SHORT"

    sup = Sup()
    result = adopt_live_tv_side(
        sup,
        {"latest_tv_action": "LONG"},
        adopted_manual=True,
    )
    assert result["force_close"] is True
    assert sup.last_tv_side == "LONG"


def test_adopt_live_tv_side_when_latest_tv_is_close():
    class Sup:
        last_tv_side = "SHORT"
        current_side = "LONG"

    sup = Sup()
    adopt_live_tv_side(sup, {"latest_tv_action": "CLOSE_PROTECT"})
    assert sup.last_tv_side == "LONG"


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
