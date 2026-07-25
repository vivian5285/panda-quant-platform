"""Smart re-entry policy — whitepaper v2.0 (2026-07-25)."""

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
    reentry_within_window,
    reset_reentry_state,
    tier_for_attempt,
    tv_deviation_ok,
)
from app.core.breathing_profile import ETH_PROFILE, XAU_PROFILE, trail_distance_multiplier
from app.core.breathing_stop import apply_breathing_tick, compute_temp_tv_stop
from app.core.trend_tier_params import (
    RADAR_ARM_TP1_PCT,
    adx_to_tier,
    params_for_tier,
    radar_arm_trigger_price,
)


def test_whitepaper_arm_and_max_reentry():
    assert arm_tp1_pct_for_attempt(0) == RADAR_ARM_TP1_PCT
    assert arm_tp1_pct_for_attempt(1) == 0.85
    assert next_attempt_arm_pct(0.50) == 0.85
    assert MAX_REENTRY == 1
    assert MAX_TIER_INDEX == 2
    assert ARM_TP1_PCTS == (0.85,)


def test_adx_tiers():
    assert adx_to_tier(15) == 0
    assert adx_to_tier(20) == 1
    assert adx_to_tier(30) == 1
    assert adx_to_tier(31) == 2
    assert adx_to_tier(None) == 1


def test_eth_xau_mid_tier_params():
    e1 = tier_for_attempt(0, "ETHUSDT", adx_tier=1)
    assert e1.tier_label == "中趋势"
    assert e1.arm_tp1_pct == 0.85
    assert e1.early_breakeven_atr == 0.5
    assert e1.step_trigger_atr == 0.50
    assert e1.step_advance_atr == 0.35
    assert e1.coef_min == 2.0 and e1.coef_max == 2.5
    assert e1.hard_buffer == 1.2
    assert e1.reentry_bars == 2

    x1 = tier_for_attempt(0, "XAUUSDT", adx_tier=1)
    assert x1.step_trigger_atr == 0.40
    assert x1.step_advance_atr == 0.30
    assert x1.coef_min == 1.8 and x1.coef_max == 2.2
    assert x1.reentry_bars == 3

    # Reentry attempt loosens +1 tier
    e_re = tier_for_attempt(1, "ETHUSDT", adx_tier=1)
    assert e_re.radar_tier == 2
    assert e_re.step_trigger_atr == 0.60
    assert e_re.hard_buffer == 1.3

    e0 = params_for_tier(0, "ETHUSDT")
    assert e0.hard_buffer == 1.1
    assert e0.trail_coef_min == 1.2 and e0.trail_coef_max == 1.5


def test_arm_distance_path_85_to_tp1():
    atr = 10.0
    # ETH tp1_atr=1.35 → path 85% = 11.475
    d = arm_distance(atr, 0, "ETHUSDT", adx_tier=1)
    assert abs(d - 1.35 * 10 * 0.85) < 1e-9
    # Explicit entry/tp1 path
    trig = radar_arm_trigger_price(side="LONG", entry=2000, tp1=2100, atr=10)
    assert abs(trig - (2000 + 0.85 * 100)) < 1e-9
    d2 = arm_distance(atr, 0, "ETHUSDT", entry=2000, tp1=2100)
    assert abs(d2 - 85.0) < 1e-9


def test_hard_stop_tier_buffer():
    # TV 1900/1880 dist=20; mid buffer 1.2 → fill 1900 → 1876
    assert abs(compute_temp_tv_stop(1900, "LONG", 1880, tv_entry=1900, trend_tier=1) - 1876) < 1e-9
    # weak 1.1 → 1878
    assert abs(compute_temp_tv_stop(1900, "LONG", 1880, tv_entry=1900, trend_tier=0) - 1878) < 1e-9
    # strong 1.3 → 1874
    assert abs(compute_temp_tv_stop(1900, "LONG", 1880, tv_entry=1900, trend_tier=2) - 1874) < 1e-9


def test_dual_insurance_reentry_price():
    assert abs(limit_reentry_price("LONG", 2000) - 2000 * 0.997) < 1e-9
    assert abs(limit_reentry_price("SHORT", 2000) - 2000 * 1.003) < 1e-9
    assert tv_deviation_ok(2000, 2000)
    assert not tv_deviation_ok(2030, 2000)

    k5 = [[0, "0", "2010", "1980", "2000", "0"]]
    px, meta = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT", klines_5m=k5,
    )
    assert meta["source"] == "dual_min"
    assert abs(px - (1980 + 0.01)) < 1e-9
    assert px < 2000

    # Must also beat last entry when provided
    px_bad, m_bad = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT", klines_5m=k5, last_entry=1970,
    )
    assert px_bad == 0.0 and m_bad["reason"] == "not_better_than_entry"

    px_ok, m_ok = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT", klines_5m=k5, last_entry=1990,
    )
    assert px_ok > 0 and m_ok["reason"] == "ok"

    px_s, meta_s = compute_optimal_reentry_price(
        side="SHORT", tv_px=2000, symbol="ETHUSDT", klines_5m=k5,
    )
    assert meta_s["source"] == "dual_max"
    assert abs(px_s - (2010 - 0.01)) < 1e-9

    shallow = [[0, "0", "2010", "1995", "2000", "0"]]
    px_tv, m_tv = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT", klines_5m=shallow,
    )
    assert m_tv["source"] == "dual_min"
    assert abs(px_tv - 2000 * 0.997) < 1e-9

    px_f, m_f = compute_optimal_reentry_price(
        side="LONG", tv_px=2000, symbol="ETHUSDT",
    )
    assert m_f["source"] == "tv_pct_only"
    assert abs(px_f - 2000 * 0.997) < 1e-9


def test_close_allows_reentry_zones_and_window():
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
    ok, m = close_allows_reentry(
        side="LONG", entry=100, close_px=102, atr=10, symbol="ETHUSDT", close_track="hard",
    )
    assert not ok and m["reason"] == "hard_stop_no_reentry"
    ok, m = close_allows_reentry(
        side="LONG", entry=100, close_px=102, atr=10, symbol="ETHUSDT",
        close_track="radar", reentry_attempt=1,
    )
    assert not ok and m["reason"] == "max_reentry_once"

    # Window: ETH 2×90m = 10800s
    import time
    now = time.time()
    ok_w, wm = reentry_within_window(flat_ts=now - 100, now_ts=now, symbol="ETHUSDT")
    assert ok_w and wm["reason"] == "ok"
    ok_w, wm = reentry_within_window(flat_ts=now - 20000, now_ts=now, symbol="ETHUSDT")
    assert not ok_w and wm["reason"] == "window_expired"

    ok, m = close_allows_reentry(
        side="LONG", entry=100, close_px=102, atr=10, symbol="ETHUSDT",
        close_track="radar", flat_ts=now - 20000, now_ts=now,
    )
    assert not ok and m["reason"] == "window_expired"

    ok, _ = close_allows_reentry(
        side="SHORT", entry=4000, close_px=3997, atr=10, symbol="XAUUSDT", close_track="radar",
    )
    assert ok
    ok, m = close_allows_reentry(
        side="SHORT", entry=4000, close_px=3996, atr=10, symbol="XAUUSDT", close_track="radar",
    )
    assert not ok


def test_classify_stop_track():
    assert classify_stop_track(close_action="CLOSE_BREATH_STOP") == "radar"
    assert classify_stop_track(
        fill_px=1910, frozen_hard_px=1910, radar_sl_px=1900, side="SHORT",
    ) == "hard"
    assert classify_stop_track(
        fill_px=1900, frozen_hard_px=1910, radar_sl_px=1900, side="SHORT",
    ) == "radar"


def test_reset_reentry_state():
    st = reset_reentry_state("XAUUSDT", adx_tier=1)
    assert st["reentry_attempt"] == 0
    assert st["reentry_arm_tp1_pct"] == 0.85
    assert st["active_early_be_atr"] == 0.5
    assert st["active_coef_min"] == 1.8
    assert st["active_coef_max"] == 2.2
    assert st["reentry_tier_label"] == "中趋势"
    assert st["reentry_pending"] is False
    assert st["trend_tier"] == 1


def test_profile_mid_tier_defaults():
    assert ETH_PROFILE.early_breakeven_atr == 0.5
    assert ETH_PROFILE.step_trigger_atr == 0.50
    assert ETH_PROFILE.step_advance_atr == 0.35
    assert ETH_PROFILE.coef_min == 2.0 and ETH_PROFILE.coef_max == 2.5
    assert XAU_PROFILE.step_trigger_atr == 0.40
    assert XAU_PROFILE.step_advance_atr == 0.30
    assert XAU_PROFILE.coef_min == 1.8 and XAU_PROFILE.coef_max == 2.2
    assert XAU_PROFILE.early_breakeven_atr == 0.5


def test_radar_waits_until_tp1_path_then_activates():
    entry, atr = 2000.0, 20.0
    tp1 = entry + 1.35 * atr  # 2027
    initial_stop = entry - 1.5 * atr
    # Below arm → waiting
    tick = apply_breathing_tick(
        side="LONG",
        price=entry + 5,
        entry_price=entry,
        initial_atr=atr,
        initial_stop=initial_stop,
        current_stop=initial_stop,
        best_price=entry + 5,
        breakeven_phase=False,
        symbol="ETHUSDT",
        arm_tp1_pct=0.85,
        tp1_price=tp1,
        radar_activated=False,
        breath_tp1_tp2_atr=1.2,
        step_trigger_atr=0.50,
        step_advance_atr=0.35,
        early_breakeven_atr=0.5,
        coef_min=2.0,
        coef_max=2.5,
    )
    assert tick["meta"]["event"] == "waiting_arm"
    assert abs(tick["current_sl"] - initial_stop) < 1e-9

    arm_px = entry + 0.85 * (tp1 - entry)
    tick2 = apply_breathing_tick(
        side="LONG",
        price=arm_px,
        entry_price=entry,
        initial_atr=atr,
        initial_stop=initial_stop,
        current_stop=initial_stop,
        best_price=arm_px,
        breakeven_phase=False,
        symbol="ETHUSDT",
        arm_tp1_pct=0.85,
        tp1_price=tp1,
        radar_activated=False,
        breath_tp1_tp2_atr=1.2,
        step_trigger_atr=0.50,
        step_advance_atr=0.35,
        early_breakeven_atr=0.5,
        coef_min=2.0,
        coef_max=2.5,
    )
    assert tick2["meta"].get("just_activated") or tick2["event"] == "radar_activate"
    assert tick2["current_sl"] >= entry + 0.5 * atr - 1e-9


def test_tier_coef_band_in_breathing_tick():
    assert abs(
        trail_distance_multiplier(2.5, ETH_PROFILE, coef_min=2.5, coef_max=3.5) - 3.5
    ) < 1e-9
