"""Deprecated absolute mid/TP2 arm — superseded by test_radar_arm_adx.py."""

from __future__ import annotations

from app.core.trend_tier_params import radar_arm_absolute_trigger


def test_absolute_arm_purged():
    assert radar_arm_absolute_trigger(1925.65, 1955.0, is_reentry=False) == 0.0
    assert radar_arm_absolute_trigger(1925.65, 1955.0, is_reentry=True) == 0.0
