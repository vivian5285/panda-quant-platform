"""VPS continuous-ladder radar — checklist §六 (all exchanges)."""

import pytest

from app.core.radar_trail import (
    RADAR_ARM_PROGRESS,
    RADAR_LOCK_ATR,
    RADAR_STEP_ATR,
    RADAR_TP1_FLOOR_ATR,
    RADAR_TP2_FLOOR_ATR,
    RADAR_TP3_TRAIL_ATR,
    REGIME_RADAR,
)
from app.core.vps_radar_stages import (
    detect_radar_stage,
    compute_ladder_radar_sl,
    compute_vps_radar_sl,
    apply_radar_sl_direction,
    is_favorable_radar_sl,
    tp1_filled_from_consumed,
    BREAKEVEN_BUFFER_PCT,
)


ENTRY = 1800.0
TP1 = 1840.5
TP2 = 1875.0
TP3 = 1908.0
ATR = 30.0


def test_regime_table_unified_continuous_ladder():
    """All regimes share checklist ladder params (regime key inert)."""
    for r in (1, 2, 3, 4):
        assert REGIME_RADAR[r] == {
            "activation": RADAR_ARM_PROGRESS,
            "move_step": RADAR_STEP_ATR,
            "trail_offset": RADAR_LOCK_ATR,
        }
    assert RADAR_ARM_PROGRESS == 0.85
    assert RADAR_STEP_ATR == 0.50
    assert RADAR_LOCK_ATR == 0.30
    assert RADAR_TP1_FLOOR_ATR == 0.50
    assert RADAR_TP2_FLOOR_ATR == 1.50
    assert RADAR_TP3_TRAIL_ATR == 2.00


def test_stage0_before_arm():
    px = ENTRY + (TP1 - ENTRY) * 0.50
    assert detect_radar_stage(ENTRY, px, "LONG", TP1, TP2, TP3) == 0


def test_stage1_on_arm_path():
    arm_px = ENTRY + RADAR_ARM_PROGRESS * (TP1 - ENTRY) + 0.01
    assert detect_radar_stage(ENTRY, arm_px, "LONG", TP1, TP2, TP3, armed=True) == 1


def test_stage3_at_tp1():
    assert detect_radar_stage(ENTRY, TP1, "LONG", TP1, TP2, TP3, armed=True) == 3


def test_stage4_at_tp2():
    assert detect_radar_stage(ENTRY, TP2, "LONG", TP1, TP2, TP3, armed=True) == 4


def test_stage5_at_tp3():
    assert detect_radar_stage(ENTRY, TP3, "LONG", TP1, TP2, TP3, armed=True) == 5


def test_radar_sl_only_moves_up_for_long():
    assert apply_radar_sl_direction(1800.0, 1810.0, "LONG") == 1810.0
    assert apply_radar_sl_direction(1810.0, 1805.0, "LONG") == 1810.0


def test_compute_ladder_arms_at_85_path():
    arm_px = ENTRY + RADAR_ARM_PROGRESS * (TP1 - ENTRY) + 0.01
    raw, stage, meta = compute_ladder_radar_sl(
        entry=ENTRY, curr_px=arm_px, best_price=arm_px, atr=ATR, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3, activated=False, step_count=0,
    )
    assert meta["activated"] is True
    assert meta["event"] == "radar_arm"
    # Same tick may also advance steps if price already past 0.5ATR triggers
    assert stage in (1, 2)
    assert raw >= ENTRY * (1.0 + BREAKEVEN_BUFFER_PCT) - 1e-9


def test_tp1_floor_and_tp2_floor():
    raw_tp1, stage1, _ = compute_ladder_radar_sl(
        entry=ENTRY, curr_px=TP1, best_price=TP1, atr=ATR, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3, activated=True, step_count=0,
    )
    assert stage1 == 3
    assert raw_tp1 >= ENTRY + RADAR_TP1_FLOOR_ATR * ATR - 1e-9

    raw_tp2, stage2, _ = compute_ladder_radar_sl(
        entry=ENTRY, curr_px=TP2, best_price=TP2, atr=ATR, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3, activated=True, step_count=2,
    )
    assert stage2 == 4
    assert raw_tp2 >= ENTRY + RADAR_TP2_FLOOR_ATR * ATR - 1e-9


def test_tp3_trail_peak_minus_2atr():
    peak = 1910.0
    raw, stage, meta = compute_ladder_radar_sl(
        entry=ENTRY, curr_px=TP3, best_price=peak, atr=ATR, side="LONG",
        tp1=TP1, tp2=TP2, tp3=TP3, activated=True, step_count=5,
    )
    assert stage == 5
    assert meta["mode"] == "tp3_trail"
    assert abs(raw - (peak - RADAR_TP3_TRAIL_ATR * ATR)) < 0.05


def test_short_symmetric_arm_and_floor():
    entry, tp1, tp2, tp3, atr = 3300.0, 3250.0, 3200.0, 3150.0, 30.0
    arm_px = entry - RADAR_ARM_PROGRESS * (entry - tp1) - 0.01
    raw, _, meta = compute_ladder_radar_sl(
        entry=entry, curr_px=arm_px, best_price=arm_px, atr=atr, side="SHORT",
        tp1=tp1, tp2=tp2, tp3=tp3, activated=False, step_count=0,
    )
    assert meta["activated"] is True
    raw_tp1, stage, _ = compute_ladder_radar_sl(
        entry=entry, curr_px=tp1, best_price=tp1, atr=atr, side="SHORT",
        tp1=tp1, tp2=tp2, tp3=tp3, activated=True, step_count=0,
    )
    assert stage == 3
    assert raw_tp1 <= entry - RADAR_TP1_FLOOR_ATR * atr + 1e-9


def test_vps_radar_pass_state_arms():
    out = compute_vps_radar_sl(
        entry=ENTRY, curr_px=ENTRY + RADAR_ARM_PROGRESS * (TP1 - ENTRY) + 0.01,
        best_price=ENTRY + RADAR_ARM_PROGRESS * (TP1 - ENTRY) + 0.01,
        atr=ATR, side="LONG", tp1=TP1, tp2=TP2, tp3=TP3,
        old_sl=0, hard_sl=1750, clamp_fn=lambda x: x,
        activated=False, step_count=0,
    )
    assert out["activated"] is True
    assert out["radar_sl"] > 0
    assert is_favorable_radar_sl(out["radar_sl"], ENTRY, "LONG") or out["radar_sl"] >= ENTRY


def test_tp1_filled_from_consumed():
    assert tp1_filled_from_consumed([]) is False
    assert tp1_filled_from_consumed([1]) is True
    assert tp1_filled_from_consumed([2]) is True
