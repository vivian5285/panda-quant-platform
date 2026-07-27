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
    """§14: all regimes share fixed 0.85 arm; no ladder move_step/trail_offset."""
    for r in (1, 2, 3, 4):
        assert REGIME_RADAR[r]["activation"] == pytest.approx(0.85)
        assert "move_step" not in REGIME_RADAR[r]
        assert "trail_offset" not in REGIME_RADAR[r]
    assert regime_radar_activation(3) == pytest.approx(0.85)


def test_merge_regime_radar_overlays_looser_params():
    base = {3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60}}
    merged = merge_regime_radar(base)
    assert merged[3]["activation"] == REGIME_RADAR[3]["activation"]
    assert merged[3]["margin"] == 0.35
    assert "move_step" not in merged[3]


def test_trail_distance_uses_tp1_floor_when_atr_tight():
    tp1_dist = 50.0
    atr_trail = 30.0 * 0.9  # 27
    min_trail = tp1_dist * RADAR_MIN_TRAIL_TP1_FRAC  # 11
    assert trail_distance(30.0, 0.9, tp1_dist) == pytest.approx(atr_trail)
    assert trail_distance(10.0, 0.5, tp1_dist) == pytest.approx(min_trail)


def test_radar_may_arm_on_path_ratio():
    assert radar_may_arm(consumed_tp_levels=[1], progress=0.5, activation_ratio=0.50) is True
    assert radar_may_arm(consumed_tp_levels=[], progress=0.49, activation_ratio=0.50) is False
    assert radar_may_arm(consumed_tp_levels=[], progress=0.50, activation_ratio=0.50) is True
    assert radar_may_arm(consumed_tp_levels=[], progress=0.60, activation_ratio=0.50) is True
    assert radar_may_arm(
        consumed_tp_levels=[], progress=0.0, activation_ratio=0.50, radar_active=True,
    ) is True
    assert radar_may_arm(consumed_tp_levels=[2], progress=0.0, activation_ratio=0.50) is True


def test_incident_tight_tp1_effective_activation_blocks_early_path():
    """Fixed 0.85 arm — low progress never arms."""
    entry, tp1, atr = 1845.91, 1849.6471230213, 4.982830695
    eff = radar_effective_activation(1, entry, tp1, atr)
    assert eff == pytest.approx(0.85)
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
    assert d["should_arm"] is False
    px_mid = entry + 0.50 * (tp1 - entry)
    d50 = evaluate_radar_arm_gate(
        consumed_tp_levels=[],
        progress=0.50,
        regime=1,
        entry=entry,
        tp1=tp1,
        atr=atr,
        curr_px=px_mid,
        side="LONG",
        trade_opened_at=time.time() - 120,
        path_ok_streak=RADAR_ARM_CONFIRM_POLLS,
    )
    assert d50["should_arm"] is False
    assert d50["effective_activation"] == pytest.approx(0.85)


def test_path_arms_at_fixed_085_all_regimes():
    """Whitepaper: fixed 85% path; regime key inert."""
    entry, tp1, atr = 1800.0, 1900.0, 20.0
    px70 = entry + 0.70 * (tp1 - entry)
    px85 = entry + 0.85 * (tp1 - entry)
    for regime in (1, 2, 3, 4):
        d70 = evaluate_radar_arm_gate(
            consumed_tp_levels=[], progress=0.70, regime=regime,
            entry=entry, tp1=tp1, atr=atr, curr_px=px70, side="LONG",
            trade_opened_at=time.time() - 120, path_ok_streak=RADAR_ARM_CONFIRM_POLLS,
        )
        assert d70["should_arm"] is False
        d85 = evaluate_radar_arm_gate(
            consumed_tp_levels=[], progress=0.85, regime=regime,
            entry=entry, tp1=tp1, atr=atr, curr_px=px85, side="LONG",
            trade_opened_at=time.time() - 120, path_ok_streak=RADAR_ARM_CONFIRM_POLLS,
        )
        assert d85["should_arm"] is True
        assert d85["effective_activation"] == pytest.approx(0.85)


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
    assert d["should_arm"] is True
    assert d["reason"] == "tp_filled"


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
    assert d["reason"] == "open_grace"
    assert d["should_arm"] is False
    assert RADAR_OPEN_GRACE_SEC >= 15


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
    assert d1["should_arm"] is False
    d2 = evaluate_radar_arm_gate(path_ok_streak=d1["path_ok_streak"], **kwargs)
    assert d2["should_arm"] is True


def test_tp_path_progress_reaches_one_at_tp1():
    from app.core.radar_trail import tp_path_progress

    assert tp_path_progress(1818.0, 1836.0, 1836.0, "LONG") == pytest.approx(1.0)
    assert tp_path_progress(1818.0, 1833.84, 1836.0, "LONG") == pytest.approx(0.88, rel=0.01)


def test_path_arm_stage_label_only():
    from app.core.vps_radar_stages import detect_radar_stage, compute_vps_radar_sl

    entry, tp1, tp2, tp3 = 1800.0, 1900.0, 1950.0, 2000.0
    curr = entry + 0.70 * (tp1 - entry)
    # tp1_filled → stage 3 (TP1区间), not ladder SL
    assert detect_radar_stage(entry, curr, "LONG", tp1, tp2, tp3, tp1_filled=True) == 3
    with pytest.raises(RuntimeError, match="LEGACY_PURGED"):
        compute_vps_radar_sl(
            entry=entry, curr_px=curr, best_price=curr, atr=20.0, side="LONG",
            tp1=tp1, tp2=tp2, tp3=tp3, old_sl=0.0, hard_sl=1700.0,
            clamp_fn=lambda x: x, tp1_filled=True,
        )


def test_tp2_locks_stage_4():
    from app.core.vps_radar_stages import detect_radar_stage

    entry, tp1, tp2, tp3 = 1800.0, 1900.0, 1950.0, 2000.0
    assert detect_radar_stage(entry, tp2, "LONG", tp1, tp2, tp3, tp1_filled=True) == 4


def test_breakeven_floor_is_fee_cover_be():
    """Marathon: floor = fee+tick BE; TP1 consume does not widen/narrow ATR floor."""
    from app.core.radar_trail import fee_cover_breakeven_stop

    entry = 2000.0
    atr = 30.0
    before = breakeven_floor(entry, "LONG", atr, consumed_tp_levels=[], symbol="ETHUSDT")
    after = breakeven_floor(entry, "LONG", atr, consumed_tp_levels=[1], symbol="ETHUSDT")
    expect = fee_cover_breakeven_stop(entry, "LONG", "ETHUSDT")
    assert before > entry
    assert after > entry
    assert abs(before - after) < 1e-9
    assert abs(before - expect) < 1e-9
    assert before < entry + 0.5 * atr


def test_compute_radar_sl_purged():
    with pytest.raises(RuntimeError, match="LEGACY_PURGED"):
        compute_radar_sl(
            side="LONG",
            entry=2000.0,
            best_price=2040.0,
            atr=30.0,
            trail_mult=1.35,
            tp1_dist=50.0,
            consumed_tp_levels=[1],
            clamp_fn=lambda x: x,
        )


def test_stop_market_safe_clamp_long_pullback():
    """Peak best_price can push SL above mark — must clamp before placement."""
    entry = 1772.38
    best = 1806.0
    curr = 1785.0
    tp1_dist = 37.62
    trail = trail_distance(30.0, 0.9, tp1_dist)
    # Floor is fee BE (near entry); trail from peak may still sit above mark
    raw = max(best - trail, breakeven_floor(entry, "LONG", 30.0, symbol="ETHUSDT"))
    # Force an above-mark candidate if trail alone is below mark (marathon fee BE)
    if raw <= curr:
        raw = curr + 5.0
    assert raw > curr
    assert stop_would_trigger_immediately(raw, curr, "LONG") is True
    safe = clamp_stop_market_safe(raw, curr, "LONG")
    assert safe < curr
    assert stop_would_trigger_immediately(safe, curr, "LONG") is False
