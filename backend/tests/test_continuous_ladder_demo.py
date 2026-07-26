"""§14 purge: continuous-ladder demo retired; whitepaper arm + TP ratios remain."""

import math

import pytest

from app.core.radar_trail import RADAR_ARM_PROGRESS, radar_arm_trigger_price
from app.core.tp_regime_ratios import PLACEABLE_TP_LEVELS
from app.core.vps_radar_stages import (
    ATR_REFRESH_SEC,
    TP_LIMIT_TIMEOUT_SEC,
    compute_ladder_radar_sl,
    compute_vps_radar_sl,
)
from app.core.trend_tier_params import HARD_STOP_BUFFER_FIXED, RADAR_ARM_TP1_PCT


ENTRY = 1800.0
ATR = 30.0
TP1 = 1840.5


def test_legacy_ladder_demo_purged():
    with pytest.raises(RuntimeError, match="LEGACY_PURGED"):
        compute_ladder_radar_sl(
            entry=ENTRY, curr_px=TP1, best_price=TP1, atr=ATR,
            side="LONG", tp1=TP1, tp2=1875, tp3=1908,
        )
    with pytest.raises(RuntimeError, match="LEGACY_PURGED"):
        compute_vps_radar_sl(
            entry=ENTRY, curr_px=TP1, best_price=TP1, atr=ATR,
            side="LONG", tp1=TP1, tp2=1875, tp3=1908,
            old_sl=0, hard_sl=1700, clamp_fn=lambda x: x,
        )


def test_whitepaper_arm_path_not_absolute_tp1():
    arm = radar_arm_trigger_price(ENTRY, TP1, "LONG", progress=RADAR_ARM_PROGRESS)
    expect = ENTRY + RADAR_ARM_PROGRESS * (TP1 - ENTRY)
    assert abs(arm - expect) < 1e-9
    # Must NOT be absolute TP1 × 0.85
    assert abs(arm - TP1 * 0.85) > 1.0


def test_placeable_tp_and_timers():
    assert PLACEABLE_TP_LEVELS == frozenset({1, 2})
    assert ATR_REFRESH_SEC == 300.0
    assert TP_LIMIT_TIMEOUT_SEC == 300.0
    assert RADAR_ARM_TP1_PCT == 0.85
    assert HARD_STOP_BUFFER_FIXED == 1.15


def test_purged_step_constants_are_nan():
    from app.core.radar_trail import RADAR_LOCK_ATR, RADAR_STEP_ATR, RADAR_TP2_FLOOR_ATR

    assert math.isnan(RADAR_STEP_ATR)
    assert math.isnan(RADAR_LOCK_ATR)
    assert math.isnan(RADAR_TP2_FLOOR_ATR)
