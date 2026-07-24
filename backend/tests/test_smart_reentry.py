"""Smart re-entry policy unit tests."""

from app.core.smart_reentry import (
    ARM_TP1_PCTS,
    MAX_REENTRY,
    arm_distance,
    arm_tp1_pct_for_attempt,
    classify_stop_track,
    close_allows_reentry,
    compute_optimal_reentry_price,
    limit_reentry_price,
    next_attempt_arm_pct,
    reset_reentry_state,
    tier_for_attempt,
    tv_deviation_ok,
)
from app.core.breathing_profile import ETH_PROFILE, XAU_PROFILE


def test_arm_ladder_and_growth():
    assert arm_tp1_pct_for_attempt(0) == 0.50
    assert arm_tp1_pct_for_attempt(1) == 0.65
    assert arm_tp1_pct_for_attempt(2) == 0.80
    assert arm_tp1_pct_for_attempt(3) == 0.95
    assert next_attempt_arm_pct(0.50) == 0.65
    assert abs(next_attempt_arm_pct(0.80) - 0.95) < 1e-9  # 1.04 capped
    assert MAX_REENTRY == 3
    assert ARM_TP1_PCTS[-1] == 0.95


def test_eth_xau_tiers():
    e0 = tier_for_attempt(0, "ETHUSDT")
    assert e0.early_breakeven_atr == 0.50
    assert e0.step_trigger_atr == 0.75
    assert e0.step_advance_atr == 0.40
    x0 = tier_for_attempt(0, "XAUUSDT")
    assert x0.early_breakeven_atr == 0.65
    assert x0.step_trigger_atr == 0.70
    assert x0.step_advance_atr == 0.45
    e3 = tier_for_attempt(3, "ETHUSDT")
    assert e3.early_breakeven_atr == 1.00
    assert e3.step_trigger_atr == 1.20
    x3 = tier_for_attempt(3, "XAUUSDT")
    assert x3.early_breakeven_atr == 1.20
    assert x3.step_advance_atr == 0.60


def test_arm_distance_max_of_tp1_and_trigger():
    atr = 10.0
    # ETH attempt0: TP1×0.5×10=6.75, trigger 0.75×10=7.5 → 7.5
    d = arm_distance(atr, 0, "ETHUSDT")
    assert abs(d - 7.5) < 1e-9
    # XAU attempt0: TP1×0.5×10=6.75, trigger 0.70×10=7.0 → 7.0
    dx = arm_distance(atr, 0, "XAUUSDT")
    assert abs(dx - 7.0) < 1e-9


def test_limit_and_optimal_reentry_price():
    assert abs(limit_reentry_price("LONG", 2000) - 2000 * 0.997) < 1e-9
    assert abs(limit_reentry_price("SHORT", 2000) - 2000 * 1.003) < 1e-9
    assert tv_deviation_ok(2000, 2000)
    assert not tv_deviation_ok(2030, 2000)

    # Binance-style kline: [ot, o, h, l, c, ...]
    k5 = [[0, "0", "2010", "1980", "2000", "0"]]
    px, meta = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT", klines_5m=k5,
    )
    assert meta["source"] == "kline_5m"
    assert abs(px - (1980 + 0.01)) < 1e-9
    assert px < 2000

    px_s, meta_s = compute_optimal_reentry_price(
        side="SHORT", tv_px=2000, symbol="ETHUSDT", klines_5m=k5,
    )
    assert abs(px_s - (2010 - 0.01)) < 1e-9
    assert px_s > 2000

    # Not better than TV → reject (LONG low+tick still >= TV)
    worse = [[0, "0", "2010", "2000", "2005", "0"]]  # low+tick=2000.01 >? >= TV edge
    # use low exactly at TV so low+tick > TV
    worse = [[0, "0", "2010", "2000", "2005", "0"]]
    px0, m0 = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT", klines_5m=worse,
    )
    # 2000+0.01 is not < 2000
    assert px0 == 0.0 and m0["reason"] == "not_better_than_tv"

    # Fallback when no klines
    px_f, m_f = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT",
    )
    assert m_f["source"] == "tv_pct_fallback"
    assert abs(px_f - 2000 * 0.997) < 1e-9


def test_close_allows_reentry_zones():
    # ETH LONG: entry 100, atr 10, zone +5 → close 100..105
    ok, m = close_allows_reentry(
        side="LONG", entry=100, close_px=102, atr=10, symbol="ETHUSDT", close_track="radar",
    )
    assert ok and m["reason"] == "ok"
    ok, m = close_allows_reentry(
        side="LONG", entry=100, close_px=99, atr=10, symbol="ETHUSDT", close_track="radar",
    )
    assert not ok and m["reason"] == "loss_no_reentry"
    ok, m = close_allows_reentry(
        side="LONG", entry=100, close_px=106, atr=10, symbol="ETHUSDT", close_track="radar",
    )
    assert not ok and m["reason"] == "outside_reentry_zone"
    # Hard never
    ok, m = close_allows_reentry(
        side="LONG", entry=100, close_px=102, atr=10, symbol="ETHUSDT", close_track="hard",
    )
    assert not ok and m["reason"] == "hard_stop_no_reentry"
    # XAU zone 0.3×ATR
    ok, _ = close_allows_reentry(
        side="SHORT", entry=4000, close_px=3997, atr=10, symbol="XAUUSDT", close_track="radar",
    )
    assert ok  # within 4000-3 .. 4000
    ok, m = close_allows_reentry(
        side="SHORT", entry=4000, close_px=3996, atr=10, symbol="XAUUSDT", close_track="radar",
    )
    assert not ok  # below zone


def test_classify_stop_track():
    assert classify_stop_track(close_action="CLOSE_BREATH_STOP") == "radar"
    assert classify_stop_track(
        fill_px=1910, frozen_hard_px=1910, radar_sl_px=1900, side="SHORT",
    ) == "hard"
    assert classify_stop_track(
        fill_px=1900, frozen_hard_px=1910, radar_sl_px=1900, side="SHORT",
    ) == "radar"


def test_reset_reentry_state():
    st = reset_reentry_state("XAUUSDT")
    assert st["reentry_attempt"] == 0
    assert st["reentry_arm_tp1_pct"] == 0.50
    assert st["active_early_be_atr"] == 0.65
    assert st["reentry_pending"] is False


def test_xau_profile_aligned_phase2():
    assert XAU_PROFILE.early_breakeven_atr == 0.65
    assert XAU_PROFILE.step_trigger_atr == 0.70
    assert XAU_PROFILE.step_advance_atr == 0.45
    assert XAU_PROFILE.coef_min == 1.2
    assert XAU_PROFILE.coef_max == 2.5
    assert ETH_PROFILE.early_breakeven_atr == 0.5
