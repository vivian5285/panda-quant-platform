"""Radar breakeven trailing — regime slack and TP1-first arming."""

import pytest

from app.core.radar_trail import (
    RADAR_MIN_TRAIL_TP1_FRAC,
    RADAR_PRE_TP1_ARM_PROGRESS,
    REGIME_RADAR,
    breakeven_floor,
    clamp_stop_market_safe,
    compute_radar_sl,
    merge_regime_radar,
    radar_may_arm,
    stop_would_trigger_immediately,
    trail_distance,
    tp1_distance,
)


def test_merge_regime_radar_overlays_looser_params():
    base = {3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90}}
    merged = merge_regime_radar(base)
    assert merged[3]["activation"] == REGIME_RADAR[3]["activation"]
    assert merged[3]["trail_offset"] == REGIME_RADAR[3]["trail_offset"]
    assert merged[3]["margin"] == 0.35


def test_trail_distance_uses_tp1_floor_when_atr_tight():
    tp1_dist = 50.0
    atr_trail = 30.0 * 0.9  # 27
    min_trail = tp1_dist * RADAR_MIN_TRAIL_TP1_FRAC  # 11
    assert trail_distance(30.0, 0.9, tp1_dist) == pytest.approx(atr_trail)
    assert trail_distance(10.0, 0.5, tp1_dist) == pytest.approx(min_trail)


def test_radar_may_arm_after_tp1_only():
    assert radar_may_arm(consumed_tp_levels=[1], progress=0.5, activation_ratio=0.85) is True
    assert radar_may_arm(consumed_tp_levels=[], progress=0.90, activation_ratio=0.85) is False
    assert radar_may_arm(
        consumed_tp_levels=[], progress=0.97, activation_ratio=0.85,
    ) is True
    assert radar_may_arm(
        consumed_tp_levels=[], progress=0.97, activation_ratio=0.85,
        radar_active=True,
    ) is True


def test_radar_pre_tp1_arm_threshold_is_96pct():
    assert RADAR_PRE_TP1_ARM_PROGRESS == 0.96


def test_breakeven_floor_wider_before_tp1():
    entry = 2000.0
    atr = 30.0
    before = breakeven_floor(entry, "LONG", atr, consumed_tp_levels=[])
    after = breakeven_floor(entry, "LONG", atr, consumed_tp_levels=[1])
    assert before > entry
    assert after > entry
    assert before > after


def test_compute_radar_sl_long_respects_floor_and_trail():
    entry = 2000.0
    tp1_dist = tp1_distance(entry, [2050.0], 30.0)
    trail = trail_distance(30.0, 1.35, tp1_dist)
    floor = breakeven_floor(entry, "LONG", 30.0, consumed_tp_levels=[1])

    def clamp(x):
        return x

    sl = compute_radar_sl(
        side="LONG",
        entry=entry,
        best_price=2040.0,
        atr=30.0,
        trail_mult=1.35,
        tp1_dist=tp1_dist,
        consumed_tp_levels=[1],
        clamp_fn=clamp,
    )
    assert sl == pytest.approx(max(2040.0 - trail, floor), rel=0.001)
    assert sl >= floor


def test_compute_radar_sl_short_respects_floor_and_trail():
    entry = 2000.0
    tp1_dist = tp1_distance(entry, [1950.0], 30.0)
    trail = trail_distance(30.0, 1.35, tp1_dist)
    floor = breakeven_floor(entry, "SHORT", 30.0, consumed_tp_levels=[1])

    def clamp(x):
        return x

    sl = compute_radar_sl(
        side="SHORT",
        entry=entry,
        best_price=1960.0,
        atr=30.0,
        trail_mult=1.35,
        tp1_dist=tp1_dist,
        consumed_tp_levels=[1],
        clamp_fn=clamp,
    )
    assert sl == pytest.approx(min(1960.0 + trail, floor), rel=0.001)
    assert sl <= floor


def test_stop_market_safe_clamp_long_pullback():
    """Peak best_price can push SL above mark — must clamp before placement."""
    entry = 1772.38
    best = 1806.0
    curr = 1785.0
    tp1_dist = 37.62
    trail = trail_distance(30.0, 1.35, tp1_dist)
    raw = max(best - trail, breakeven_floor(entry, "LONG", 30.0))
    assert raw > curr
    assert stop_would_trigger_immediately(raw, curr, "LONG") is True
    safe = clamp_stop_market_safe(raw, curr, "LONG")
    assert safe < curr
    assert stop_would_trigger_immediately(safe, curr, "LONG") is False
