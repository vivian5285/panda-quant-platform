"""VPS 8-stage radar trailing — v6.9.103 spec."""

import pytest

from app.core.vps_radar_stages import (
    detect_radar_stage,
    compute_vps_radar_sl,
    apply_radar_sl_direction,
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
