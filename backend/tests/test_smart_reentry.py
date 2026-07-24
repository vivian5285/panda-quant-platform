"""Smart re-entry policy unit tests — final plan 2026-07-25."""

from app.core.smart_reentry import (
    ARM_TP1_PCTS,
    MAX_REENTRY,
    MAX_TIER_INDEX,
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
from app.core.breathing_profile import ETH_PROFILE, XAU_PROFILE, trail_distance_multiplier
from app.core.breathing_stop import apply_breathing_tick


def test_arm_ladder_and_growth():
    assert arm_tp1_pct_for_attempt(0) == 0.50
    assert arm_tp1_pct_for_attempt(1) == 0.65
    assert arm_tp1_pct_for_attempt(2) == 0.80
    assert arm_tp1_pct_for_attempt(3) == 0.90
    assert arm_tp1_pct_for_attempt(4) == 0.95
    assert next_attempt_arm_pct(0.50) == 0.65
    assert abs(next_attempt_arm_pct(0.80) - 0.95) < 1e-9  # 1.04 capped
    assert MAX_REENTRY == 4
    assert MAX_TIER_INDEX == 4
    assert ARM_TP1_PCTS == (0.50, 0.65, 0.80, 0.90, 0.95)


def test_eth_xau_tiers():
    e0 = tier_for_attempt(0, "ETHUSDT")
    assert e0.tier_label == "1.0"
    assert e0.early_breakeven_atr == 0.50
    assert e0.step_trigger_atr == 0.75
    assert e0.step_advance_atr == 0.40
    assert e0.coef_min == 1.2 and e0.coef_max == 2.5

    x0 = tier_for_attempt(0, "XAUUSDT")
    assert x0.early_breakeven_atr == 0.65
    assert x0.step_trigger_atr == 0.70
    assert x0.step_advance_atr == 0.45
    assert x0.coef_min == 1.2 and x0.coef_max == 2.5

    e3 = tier_for_attempt(3, "ETHUSDT")
    assert e3.tier_label == "4.0"
    assert e3.early_breakeven_atr == 1.05
    assert e3.step_trigger_atr == 1.25
    assert e3.step_advance_atr == 0.58
    assert e3.coef_min == 1.8 and e3.coef_max == 3.2
    assert e3.arm_tp1_pct == 0.90

    e4 = tier_for_attempt(4, "ETHUSDT")
    assert e4.tier_label == "5.0"
    assert e4.early_breakeven_atr == 1.30
    assert e4.coef_min == 2.0 and e4.coef_max == 3.5
    assert e4.arm_tp1_pct == 0.95

    x3 = tier_for_attempt(3, "XAUUSDT")
    assert x3.early_breakeven_atr == 1.30
    assert x3.step_advance_atr == 0.64
    x4 = tier_for_attempt(4, "XAUUSDT")
    assert x4.early_breakeven_atr == 1.55
    assert x4.step_trigger_atr == 1.30
    assert x4.step_advance_atr == 0.70
    assert x4.coef_max == 3.5


def test_arm_distance_max_of_tp1_and_trigger():
    atr = 10.0
    # ETH attempt0: TP1×0.5×10=6.75, trigger 0.75×10=7.5 → 7.5
    d = arm_distance(atr, 0, "ETHUSDT")
    assert abs(d - 7.5) < 1e-9
    # XAU attempt0: TP1×0.5×10=6.75, trigger 0.70×10=7.0 → 7.0
    dx = arm_distance(atr, 0, "XAUUSDT")
    assert abs(dx - 7.0) < 1e-9


def test_dual_insurance_reentry_price():
    assert abs(limit_reentry_price("LONG", 2000) - 2000 * 0.997) < 1e-9
    assert abs(limit_reentry_price("SHORT", 2000) - 2000 * 1.003) < 1e-9
    assert tv_deviation_ok(2000, 2000)
    assert not tv_deviation_ok(2030, 2000)

    # Binance-style kline: [ot, o, h, l, c, ...]
    # LONG: min(1980.01, 1994) = 1980.01 → dual_min
    k5 = [[0, "0", "2010", "1980", "2000", "0"]]
    px, meta = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT", klines_5m=k5,
    )
    assert meta["source"] == "dual_min"
    assert abs(px - (1980 + 0.01)) < 1e-9
    assert px < 2000

    # SHORT: max(2009.99, 2006) = 2009.99 → dual_max
    px_s, meta_s = compute_optimal_reentry_price(
        side="SHORT", tv_px=2000, symbol="ETHUSDT", klines_5m=k5,
    )
    assert meta_s["source"] == "dual_max"
    assert abs(px_s - (2010 - 0.01)) < 1e-9
    assert px_s > 2000

    # LONG: kline worse than TV% → pick TV×0.997 via dual_min
    shallow = [[0, "0", "2010", "1995", "2000", "0"]]  # low+tick=1995.01 > 1994
    px_tv, m_tv = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT", klines_5m=shallow,
    )
    assert m_tv["source"] == "dual_min"
    assert abs(px_tv - 2000 * 0.997) < 1e-9

    # Fallback when no klines
    px_f, m_f = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT",
    )
    assert m_f["source"] == "tv_pct_only"
    assert abs(px_f - 2000 * 0.997) < 1e-9

    # 3m fallback when 5m missing
    k3 = [[0, "0", "2008", "1975", "1990", "0"]]
    px3, m3 = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT", klines_3m=k3,
    )
    assert m3["kline_source"] == "3m"
    assert m3["source"] == "dual_min"
    assert abs(px3 - (1975 + 0.01)) < 1e-9

    # Candidate not better than TV (degenerate: tv_px invalid already covered; force equal via 0 tick edge)
    px_bad, m_bad = compute_optimal_reentry_price(
        side="LONG", tv_px=0, symbol="ETHUSDT", klines_5m=k5,
    )
    assert px_bad == 0.0 and m_bad["reason"] == "bad_inputs"


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
    assert st["active_coef_min"] == 1.2
    assert st["active_coef_max"] == 2.5
    assert st["reentry_tier_label"] == "1.0"
    assert st["reentry_pending"] is False


def test_xau_profile_aligned_phase2():
    assert XAU_PROFILE.early_breakeven_atr == 0.65
    assert XAU_PROFILE.step_trigger_atr == 0.70
    assert XAU_PROFILE.step_advance_atr == 0.45
    assert XAU_PROFILE.coef_min == 1.2
    assert XAU_PROFILE.coef_max == 2.5
    assert ETH_PROFILE.early_breakeven_atr == 0.5


def test_tier_coef_band_in_breathing_tick():
    """Tier 5.0 band 2.0~3.5 must remap trail coef vs profile 1.2~2.5."""
    # At ratio ceiling → profile max 2.5; tier5 max 3.5
    assert abs(trail_distance_multiplier(2.5, ETH_PROFILE) - 2.5) < 1e-9
    assert abs(
        trail_distance_multiplier(2.5, ETH_PROFILE, coef_min=2.0, coef_max=3.5) - 3.5
    ) < 1e-9

    tick = apply_breathing_tick(
        side="LONG",
        price=2100,
        entry_price=2000,
        initial_atr=20,
        initial_stop=1970,
        current_stop=1970,
        best_price=2100,
        breakeven_phase=True,
        symbol="ETHUSDT",
        smooth_ratio=2.5,
        coef_min=2.0,
        coef_max=3.5,
        arm_tp1_pct=0.95,
        early_breakeven_atr=1.30,
        step_trigger_atr=1.40,
        step_advance_atr=0.64,
    )
    assert abs(tick["breathing_coefficient"] - 3.5) < 1e-9
    assert abs(tick["meta"]["coef_min"] - 2.0) < 1e-9
    assert abs(tick["meta"]["coef_max"] - 3.5) < 1e-9
