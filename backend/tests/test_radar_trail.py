"""Radar breakeven trailing — path-to-TP1 arming by regime."""

import time

import pytest

from app.core.radar_trail import (
    RADAR_ARM_CONFIRM_POLLS,
    RADAR_MIN_TRAIL_TP1_FRAC,
    RADAR_OPEN_GRACE_SEC,
    REGIME_RADAR,
    breakeven_floor,
    clamp_stop_market_safe,
    compute_radar_sl,
    evaluate_radar_arm_gate,
    merge_regime_radar,
    radar_effective_activation,
    radar_may_arm,
    regime_radar_activation,
    stop_would_trigger_immediately,
    trail_distance,
    tp1_distance,
)


def test_regime_activation_table():
    """Screenshot V2: R1=85% … R4=70%; move_step / breath ATR per regime."""
    assert REGIME_RADAR[1]["activation"] == pytest.approx(0.85)
    assert REGIME_RADAR[2]["activation"] == pytest.approx(0.80)
    assert REGIME_RADAR[3]["activation"] == pytest.approx(0.75)
    assert REGIME_RADAR[4]["activation"] == pytest.approx(0.70)
    assert REGIME_RADAR[4]["move_step"] == pytest.approx(0.20)
    assert REGIME_RADAR[1]["trail_offset"] == pytest.approx(1.00)
    assert regime_radar_activation(3) == pytest.approx(0.75)


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


def test_radar_may_arm_on_path_ratio():
    assert radar_may_arm(consumed_tp_levels=[1], progress=0.5, activation_ratio=0.85) is True
    assert radar_may_arm(consumed_tp_levels=[], progress=0.84, activation_ratio=0.85) is False
    assert radar_may_arm(consumed_tp_levels=[], progress=0.85, activation_ratio=0.85) is True
    assert radar_may_arm(consumed_tp_levels=[], progress=0.90, activation_ratio=0.85) is True
    assert radar_may_arm(
        consumed_tp_levels=[], progress=0.0, activation_ratio=0.85, radar_active=True,
    ) is True
    assert radar_may_arm(consumed_tp_levels=[2], progress=0.0, activation_ratio=0.85) is True


def test_incident_tight_tp1_effective_activation_blocks_early_path():
    """Tight TP1 span → effective ≥92%; 30%/85% of tiny span must not arm without floor."""
    entry, tp1, atr = 1845.91, 1849.6471230213, 4.982830695
    eff = radar_effective_activation(1, entry, tp1, atr)
    assert eff >= 0.92
    d = evaluate_radar_arm_gate(
        consumed_tp_levels=[],
        progress=0.30,
        regime=1,
        entry=entry,
        tp1=tp1,
        atr=atr,
        curr_px=1847.05,
        side="LONG",
        trade_opened_at=time.time() - 120,
        path_ok_streak=0,
    )
    assert d["arm"] is False
    px_85 = entry + 0.85 * (tp1 - entry)
    d85 = evaluate_radar_arm_gate(
        consumed_tp_levels=[],
        progress=0.85,
        regime=1,
        entry=entry,
        tp1=tp1,
        atr=atr,
        curr_px=px_85,
        side="LONG",
        trade_opened_at=time.time() - 120,
        path_ok_streak=RADAR_ARM_CONFIRM_POLLS,
    )
    assert d85["arm"] is False
    assert d85["activation_effective"] >= 0.92


def test_path_regime_arms_on_healthy_span():
    """Healthy TP1 span: R3 arms at 75% path + confirms."""
    entry, tp1, atr = 1800.0, 1900.0, 20.0
    px = entry + 0.75 * (tp1 - entry)
    d = evaluate_radar_arm_gate(
        consumed_tp_levels=[],
        progress=0.75,
        regime=3,
        entry=entry,
        tp1=tp1,
        atr=atr,
        curr_px=px,
        side="LONG",
        trade_opened_at=time.time() - 120,
        path_ok_streak=RADAR_ARM_CONFIRM_POLLS,
    )
    assert d["arm"] is True
    assert d["arm_reason"] == "path_effective"
    assert d["activation_base"] == pytest.approx(0.75)
    assert d["move_step"] == pytest.approx(0.25)
    assert d["trail_offset"] == pytest.approx(0.65)


def test_r4_arms_earlier_than_r1():
    entry, tp1, atr = 1800.0, 1900.0, 20.0
    px = entry + 0.72 * (tp1 - entry)
    d4 = evaluate_radar_arm_gate(
        consumed_tp_levels=[], progress=0.72, regime=4,
        entry=entry, tp1=tp1, atr=atr, curr_px=px, side="LONG",
        trade_opened_at=time.time() - 120, path_ok_streak=RADAR_ARM_CONFIRM_POLLS,
    )
    d1 = evaluate_radar_arm_gate(
        consumed_tp_levels=[], progress=0.72, regime=1,
        entry=entry, tp1=tp1, atr=atr, curr_px=px, side="LONG",
        trade_opened_at=time.time() - 120, path_ok_streak=RADAR_ARM_CONFIRM_POLLS,
    )
    assert d4["arm"] is True
    assert d1["arm"] is False


def test_tp1_fill_arms_immediately():
    d = evaluate_radar_arm_gate(
        consumed_tp_levels=[1],
        progress=0.0,
        regime=4,
        entry=1800.0,
        tp1=1900.0,
        atr=20.0,
        curr_px=1801.0,
        side="LONG",
        trade_opened_at=time.time(),
        path_ok_streak=0,
    )
    assert d["arm"] is True
    assert d["arm_reason"] == "tp1_filled"


def test_open_grace_blocks_path_arm():
    entry, tp1, atr = 1800.0, 1900.0, 20.0
    now = time.time()
    d = evaluate_radar_arm_gate(
        consumed_tp_levels=[],
        progress=0.95,
        regime=1,
        entry=entry,
        tp1=tp1,
        atr=atr,
        curr_px=entry + 0.95 * 100,
        side="LONG",
        trade_opened_at=now - 5,
        path_ok_streak=5,
        now_ts=now,
    )
    assert d["blocked_grace"] is True
    assert d["arm"] is False
    assert RADAR_OPEN_GRACE_SEC >= 20


def test_confirm_polls_required_before_arm():
    entry, tp1, atr = 1800.0, 1900.0, 20.0
    now = time.time()
    kwargs = dict(
        consumed_tp_levels=[],
        progress=0.95,
        regime=1,
        entry=entry,
        tp1=tp1,
        atr=atr,
        curr_px=entry + 95.0,
        side="LONG",
        trade_opened_at=now - 120,
        now_ts=now,
    )
    d1 = evaluate_radar_arm_gate(path_ok_streak=0, **kwargs)
    assert d1["building_confirm"] is True
    assert d1["arm"] is False
    d2 = evaluate_radar_arm_gate(path_ok_streak=d1["path_ok_streak"], **kwargs)
    assert d2["arm"] is True


def test_tp_path_progress_reaches_one_at_tp1():
    from app.core.radar_trail import tp_path_progress

    assert tp_path_progress(1818.0, 1836.0, 1836.0, "LONG") == pytest.approx(1.0)
    assert tp_path_progress(1818.0, 1833.84, 1836.0, "LONG") == pytest.approx(0.88, rel=0.01)


def test_path_arm_stage_stays_breakeven_before_tp1():
    from app.core.vps_radar_stages import detect_radar_stage, compute_vps_radar_sl

    entry, tp1, tp2, tp3 = 1800.0, 1900.0, 1950.0, 2000.0
    curr = entry + 0.70 * (tp1 - entry)
    assert detect_radar_stage(entry, curr, "LONG", tp1, tp2, tp3, tp1_filled=True) == 1
    radar = compute_vps_radar_sl(
        entry=entry, curr_px=curr, best_price=curr, atr=20.0, side="LONG",
        tp1=tp1, tp2=tp2, tp3=tp3, old_sl=0.0, hard_sl=1700.0,
        clamp_fn=lambda x: x, tp1_filled=True,
    )
    assert radar["armed"] is True
    assert radar["stage"] == 1
    assert radar["radar_sl"] == pytest.approx(entry * 1.001, rel=0.001)


def test_tp2_locks_stage_3():
    from app.core.vps_radar_stages import detect_radar_stage

    entry, tp1, tp2, tp3 = 1800.0, 1900.0, 1950.0, 2000.0
    assert detect_radar_stage(entry, tp2, "LONG", tp1, tp2, tp3, tp1_filled=True) == 3


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
    trail = trail_distance(30.0, 0.9, tp1_dist)
    raw = max(best - trail, breakeven_floor(entry, "LONG", 30.0))
    assert raw > curr
    assert stop_would_trigger_immediately(raw, curr, "LONG") is True
    safe = clamp_stop_market_safe(raw, curr, "LONG")
    assert safe < curr
    assert stop_would_trigger_immediately(safe, curr, "LONG") is False
