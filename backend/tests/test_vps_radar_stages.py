"""VPS radar — TP1-fill activation, 5-stage trail (unified all regimes)."""

import pytest

from app.core.vps_radar_stages import (
    detect_radar_stage,
    compute_vps_radar_sl,
    apply_radar_sl_direction,
    is_favorable_radar_sl,
    tp1_filled_from_consumed,
    BREAKEVEN_BUFFER_PCT,
)


ENTRY = 1818.0
TP1 = 1836.0
TP2 = 1850.87
TP3 = 1863.96
ATR = 16.36


def test_stage0_before_tp1_fill_even_near_tp1():
    """Breathing room: price at 90% TP1 path must NOT arm radar."""
    px = ENTRY + (TP1 - ENTRY) * 0.90
    assert detect_radar_stage(ENTRY, px, "LONG", TP1, TP2, TP3, tp1_filled=False) == 0
    assert detect_radar_stage(ENTRY, TP1, "LONG", TP1, TP2, TP3, tp1_filled=False) == 0


def test_stage1_on_tp1_fill():
    assert detect_radar_stage(ENTRY, TP1, "LONG", TP1, TP2, TP3, tp1_filled=True) == 1


def test_stage2_at_halfway_tp1_to_tp2():
    px = TP1 + (TP2 - TP1) * 0.50
    assert detect_radar_stage(ENTRY, px, "LONG", TP1, TP2, TP3, tp1_filled=True) == 2


def test_stage3_at_tp2():
    assert detect_radar_stage(ENTRY, TP2, "LONG", TP1, TP2, TP3, tp1_filled=True) == 3


def test_stage4_halfway_tp2_to_tp3():
    px = TP2 + (TP3 - TP2) * 0.50
    assert detect_radar_stage(ENTRY, px, "LONG", TP1, TP2, TP3, tp1_filled=True) == 4


def test_stage5_at_tp3():
    assert detect_radar_stage(ENTRY, TP3, "LONG", TP1, TP2, TP3, tp1_filled=True) == 5


def test_radar_sl_only_moves_up_for_long():
    assert apply_radar_sl_direction(1800.0, 1810.0, "LONG") == 1810.0
    assert apply_radar_sl_direction(1810.0, 1805.0, "LONG") == 1810.0


def test_compute_radar_stage1_breakeven_needs_tp1_fill():
    px = ENTRY + (TP1 - ENTRY) * 0.99
    unarmed = compute_vps_radar_sl(
        entry=ENTRY, curr_px=px, best_price=px, atr=ATR, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3,
        old_sl=0, hard_sl=1800.0,
        clamp_fn=lambda x: x,
        tp1_filled=False,
    )
    assert unarmed["armed"] is False
    assert unarmed["stage"] == 0

    radar = compute_vps_radar_sl(
        entry=ENTRY, curr_px=px, best_price=px, atr=ATR, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3,
        old_sl=0, hard_sl=1800.0,
        clamp_fn=lambda x: x,
        tp1_filled=True,
    )
    assert radar["stage"] == 1
    assert radar["radar_sl"] == pytest.approx(ENTRY * (1.0 + BREAKEVEN_BUFFER_PCT), abs=0.02)


def test_stage2_atr_trail():
    px = TP1 + (TP2 - TP1) * 0.55
    radar = compute_vps_radar_sl(
        entry=ENTRY, curr_px=px, best_price=px, atr=ATR, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3,
        old_sl=ENTRY * (1.0 + BREAKEVEN_BUFFER_PCT), hard_sl=1800.0,
        clamp_fn=lambda x: x,
        tp1_filled=True,
        radar_latched=True,
    )
    assert radar["stage"] == 2
    assert radar["radar_sl"] == pytest.approx(px - ATR * 1.0, abs=0.02)


def test_stage_uses_peak_px_after_pullback():
    entry = 1800.0
    tp1, tp2, tp3 = 1780.0, 1770.0, 1760.0
    best = 1770.0
    rebound = 1790.0
    assert detect_radar_stage(
        entry, rebound, "SHORT", tp1, tp2, tp3, tp1_filled=True,
    ) == 1
    assert detect_radar_stage(
        entry, rebound, "SHORT", tp1, tp2, tp3, peak_px=best, tp1_filled=True,
    ) == 3


def test_short_rebound_holds_latched_radar_sl():
    entry = 1800.0
    tp1, tp2, tp3 = 1780.0, 1770.0, 1760.0
    best = 1770.0
    rebound = 1790.0
    breakeven_sl = entry * (1.0 - BREAKEVEN_BUFFER_PCT)
    hard_sl = 1870.0
    radar = compute_vps_radar_sl(
        entry=entry, curr_px=rebound, best_price=best, atr=16.0, side="SHORT",
        tp1=tp1, tp2=tp2, tp3=tp3,
        old_sl=breakeven_sl, hard_sl=hard_sl,
        clamp_fn=lambda x: x,
        radar_latched=True,
        tp1_filled=True,
    )
    assert radar["armed"] is True
    assert radar["radar_sl"] < entry
    assert radar["radar_sl"] <= breakeven_sl
    assert is_favorable_radar_sl(radar["radar_sl"], entry, "SHORT")


def test_tp1_filled_from_consumed():
    assert tp1_filled_from_consumed([]) is False
    assert tp1_filled_from_consumed([1]) is True
    assert tp1_filled_from_consumed([2]) is True
