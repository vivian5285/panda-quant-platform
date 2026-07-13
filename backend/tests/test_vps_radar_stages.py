"""VPS 8-stage radar trailing — v6.9.103 spec."""

import pytest

from app.core.vps_radar_stages import (
    detect_radar_stage,
    compute_vps_radar_sl,
    apply_radar_sl_direction,
    is_favorable_radar_sl,
)


ENTRY = 1818.0
TP1 = 1836.0
TP2 = 1850.87
TP3 = 1863.96
ATR = 16.36


def test_stage0_before_70pct_tp1():
    px = 1818 + (TP1 - 1818) * 0.65
    assert detect_radar_stage(ENTRY, px, "LONG", TP1, TP2, TP3) == 0


def test_stage1_at_70pct_tp1():
    px = 1818 + (TP1 - 1818) * 0.701
    assert detect_radar_stage(ENTRY, px, "LONG", TP1, TP2, TP3) == 1


def test_stage2_between_85_and_tp1():
    px = 1818 + (TP1 - 1818) * 0.90
    assert detect_radar_stage(ENTRY, px, "LONG", TP1, TP2, TP3) == 2


def test_stage3_at_tp1():
    assert detect_radar_stage(ENTRY, TP1, "LONG", TP1, TP2, TP3) == 3


def test_stage7_at_tp2():
    assert detect_radar_stage(ENTRY, TP2, "LONG", TP1, TP2, TP3) == 7


def test_radar_sl_only_moves_up_for_long():
    assert apply_radar_sl_direction(1800.0, 1810.0, "LONG") == 1810.0
    assert apply_radar_sl_direction(1810.0, 1805.0, "LONG") == 1810.0


def test_compute_radar_stage1_breakeven():
    px = 1818 + (TP1 - 1818) * 0.72
    radar = compute_vps_radar_sl(
        entry=ENTRY, curr_px=px, best_price=px, atr=ATR, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3,
        old_sl=0, hard_sl=1800.0,
        clamp_fn=lambda x: x,
    )
    assert radar["stage"] == 1
    assert radar["radar_sl"] > ENTRY


def test_stage_uses_peak_px_after_pullback():
    """Price rebound must not drop stage when peak_px preserves prior progress."""
    entry = 1800.0
    tp1 = 1780.0
    tp2 = 1770.0
    tp3 = 1760.0
    best = 1770.0
    rebound = 1790.0
    assert detect_radar_stage(entry, rebound, "SHORT", tp1, tp2, tp3) == 0
    assert detect_radar_stage(entry, rebound, "SHORT", tp1, tp2, tp3, peak_px=best) >= 1


def test_short_rebound_holds_latched_radar_sl():
    """SHORT: after radar arms, rebound toward entry must not revert SL to hard stop."""
    entry = 1800.0
    tp1 = 1780.0
    tp2 = 1770.0
    tp3 = 1760.0
    best = 1770.0
    rebound = 1790.0
    breakeven_sl = entry * (1.0 - 0.001)
    hard_sl = 1870.0
    radar = compute_vps_radar_sl(
        entry=entry, curr_px=rebound, best_price=best, atr=16.0, side="SHORT",
        tp1=tp1, tp2=tp2, tp3=tp3,
        old_sl=breakeven_sl, hard_sl=hard_sl,
        clamp_fn=lambda x: x,
        radar_latched=True,
    )
    assert radar["armed"] is True
    assert radar["radar_sl"] < entry
    assert radar["radar_sl"] <= breakeven_sl
    assert is_favorable_radar_sl(radar["radar_sl"], entry, "SHORT")
