"""VPS radar stages — alert helpers + §14 ladder purge."""

import math

import pytest

from app.core.radar_trail import RADAR_ARM_PROGRESS, REGIME_RADAR
from app.core.vps_radar_stages import (
    compute_ladder_radar_sl,
    compute_vps_radar_sl,
    detect_radar_stage,
    is_favorable_radar_sl,
    tp1_filled_from_consumed,
)


ENTRY = 1800.0
TP1 = 1840.5
TP2 = 1875.0
TP3 = 1908.0


def test_regime_table_no_legacy_ladder_keys():
    for r in (1, 2, 3, 4):
        assert REGIME_RADAR[r] == {"activation": RADAR_ARM_PROGRESS}
        assert "move_step" not in REGIME_RADAR[r]
        assert "trail_offset" not in REGIME_RADAR[r]
    assert RADAR_ARM_PROGRESS == 0.85


def test_legacy_ladder_sl_purged():
    with pytest.raises(RuntimeError, match="LEGACY_PURGED"):
        compute_ladder_radar_sl(
            entry=ENTRY, curr_px=TP1, best_price=TP1, atr=30,
            side="LONG", tp1=TP1, tp2=TP2, tp3=TP3,
        )
    with pytest.raises(RuntimeError, match="LEGACY_PURGED"):
        compute_vps_radar_sl(
            entry=ENTRY, curr_px=TP1, best_price=TP1, atr=30,
            side="LONG", tp1=TP1, tp2=TP2, tp3=TP3,
            old_sl=0, hard_sl=1700, clamp_fn=lambda x: x,
        )


def test_legacy_step_constants_nan():
    from app.core.radar_trail import (
        RADAR_LOCK_ATR,
        RADAR_STEP_ATR,
        RADAR_TP2_FLOOR_ATR,
        RADAR_TP3_TRAIL_ATR,
    )

    assert math.isnan(RADAR_STEP_ATR)
    assert math.isnan(RADAR_LOCK_ATR)
    assert math.isnan(RADAR_TP2_FLOOR_ATR)
    assert math.isnan(RADAR_TP3_TRAIL_ATR)


def test_stage0_before_arm():
    px = ENTRY + (TP1 - ENTRY) * 0.50
    assert detect_radar_stage(ENTRY, px, "LONG", TP1, TP2, TP3) == 0


def test_stage_armed_label():
    arm_px = ENTRY + (TP1 - ENTRY) * 0.85
    assert detect_radar_stage(ENTRY, arm_px, "LONG", TP1, TP2, TP3, armed=True) == 1


def test_stage_tp_levels():
    assert detect_radar_stage(ENTRY, TP1, "LONG", TP1, TP2, TP3, armed=True) == 3
    assert detect_radar_stage(ENTRY, TP2, "LONG", TP1, TP2, TP3, armed=True) == 4
    assert detect_radar_stage(ENTRY, TP3, "LONG", TP1, TP2, TP3, armed=True) == 5


def test_tp1_filled_from_consumed():
    assert tp1_filled_from_consumed([1]) is True
    assert tp1_filled_from_consumed([2]) is True
    assert tp1_filled_from_consumed([]) is False


def test_favorable_radar_sl():
    assert is_favorable_radar_sl(1810, ENTRY, "LONG")
    assert is_favorable_radar_sl(1790, ENTRY, "SHORT")
