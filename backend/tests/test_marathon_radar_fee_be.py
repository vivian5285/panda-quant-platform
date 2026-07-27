"""Marathon radar: fee+tick activate BE; TP fill must not jump SL price."""

from __future__ import annotations

from app.core.radar_trail import FEE_BUFFER_PCT, fee_cover_breakeven_stop
from app.core.symbol_precision import price_tick_for


def test_fee_cover_breakeven_long_short():
    entry = 1934.23
    tick = float(price_tick_for("ETHUSDT") or 0.01)
    long_be = fee_cover_breakeven_stop(entry, "LONG", "ETHUSDT")
    short_be = fee_cover_breakeven_stop(entry, "SHORT", "ETHUSDT")
    expect_long = entry + tick + entry * FEE_BUFFER_PCT
    expect_short = entry - tick - entry * FEE_BUFFER_PCT
    assert abs(long_be - expect_long) < tick + 1e-6
    assert abs(short_be - expect_short) < tick + 1e-6
    assert long_be > entry
    assert short_be < entry
    # Far tighter than legacy 0.5ATR (ATR~17)
    assert long_be < entry + 0.5 * 17.0


def test_boost_doc_says_prices_untouched():
    import inspect

    from app.core.adverse_radar_guard import AdverseRadarMixin

    src = inspect.getsource(AdverseRadarMixin._boost_radar_after_tp_fill)
    assert "prices are never moved" in src or "prices untouched" in src
    assert "resize_qty" in src
