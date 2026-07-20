"""Restart / heal must not rehang TP tiers already past by mark."""

from app.core.tp_slice_guard import (
    levels_past_by_mark,
    should_skip_rehang_tp_level,
    sanitize_tp_limit_price,
)


def test_levels_past_by_mark_long_skips_tp1_only():
    past = levels_past_by_mark(1870.0, "LONG", [1860.0, 1880.0, 1900.0])
    assert past == {1}


def test_levels_past_by_mark_long_skips_tp1_tp2():
    past = levels_past_by_mark(1885.0, "LONG", [1860.0, 1880.0, 1900.0])
    assert past == {1, 2}


def test_levels_past_by_mark_short():
    past = levels_past_by_mark(1850.0, "SHORT", [1860.0, 1840.0, 1820.0])
    assert 1 in past


def test_should_skip_price_past_tp_hard():
    skip, reason = should_skip_rehang_tp_level(
        1,
        1860.0,
        side="LONG",
        curr_px=1870.0,
        consumed=set(),
        live_qty=1.0,
        initial_qty=1.0,
        regime=3,
        tv_tps=[1860.0, 1880.0, 1900.0],
        regime_settings={},
        open_tp_prices=[],
    )
    assert skip is True
    assert reason in ("price_past_tp", "price_book_filled")


def test_sanitize_must_not_be_used_as_rehang_for_past_tp():
    """Document: if sanitize pushes, callers must refuse to place (not hang)."""
    place_px, adj = sanitize_tp_limit_price("LONG", 1860.0, 1870.0)
    assert adj.startswith("pushed") or place_px > 1870.0
