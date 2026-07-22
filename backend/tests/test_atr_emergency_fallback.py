"""Tests for ATR emergency fallback (temporary degrade, never silent)."""

from app.core.atr_emergency_fallback import (
    apply_fallback_atr,
    evaluate_emergency_atr_fallback,
    tv_implied_atr,
)


def test_tv_implied_atr_uses_1x():
    assert abs(tv_implied_atr(1930.49, 1915.6471582505) - 14.8428417495) < 1e-6


def test_fallback_on_invalid_vps_atr_when_tv_stop_present():
    d = evaluate_emergency_atr_fallback(
        vps_atr=0.0,
        atr_series=[],
        entry=1930.49,
        tv_stop_loss=1915.65,
        mismatch_streak=0,
    )
    assert d["need_fallback"] is True
    assert d["reason"] == "vps_atr_invalid_or_missing"
    assert d["pause_after_open"] is True
    assert apply_fallback_atr(d) > 0


def test_fallback_on_anomaly_floor():
    series = [100.0] * 50
    d = evaluate_emergency_atr_fallback(
        vps_atr=20.0,
        atr_series=series,
        entry=1800.0,
        tv_stop_loss=1780.0,
        mismatch_streak=0,
    )
    assert d["need_fallback"] is True
    assert d["reason"] == "vps_atr_below_median_floor"
    assert abs(apply_fallback_atr(d) - 20.0) < 1e-9


def test_fallback_requires_three_mismatch_streak():
    # ~50% mismatch
    kwargs = dict(
        vps_atr=40.0,
        atr_series=[40.0] * 20,
        entry=1800.0,
        tv_stop_loss=1740.0,  # implied=60
    )
    d1 = evaluate_emergency_atr_fallback(**kwargs, mismatch_streak=0)
    assert d1["need_fallback"] is False
    assert d1["mismatch_streak_next"] == 1

    d2 = evaluate_emergency_atr_fallback(**kwargs, mismatch_streak=1)
    assert d2["need_fallback"] is False
    assert d2["mismatch_streak_next"] == 2

    d3 = evaluate_emergency_atr_fallback(**kwargs, mismatch_streak=2)
    assert d3["need_fallback"] is True
    assert d3["reason"] == "atr_mismatch_streak_3"
    assert abs(apply_fallback_atr(d3) - 60.0) < 1e-9


def test_matched_atr_resets_streak_no_fallback():
    d = evaluate_emergency_atr_fallback(
        vps_atr=14.8491,
        atr_series=[14.8] * 20,
        entry=1930.49,
        tv_stop_loss=1915.6471582505,
        mismatch_streak=2,
    )
    assert d["need_fallback"] is False
    assert d["mismatch_streak_next"] == 0
    assert d["mismatch_pct"] < 5.0


def test_no_silent_fallback_without_tv_stop():
    d = evaluate_emergency_atr_fallback(
        vps_atr=0.0,
        atr_series=[],
        entry=1930.49,
        tv_stop_loss=None,
        mismatch_streak=5,
    )
    assert d["need_fallback"] is False
    assert apply_fallback_atr(d) == 0.0
