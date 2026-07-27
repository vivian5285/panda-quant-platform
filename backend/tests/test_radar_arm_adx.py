"""Gemini Layer-1 radar arm: ADX discrete 70%/80%/90% × (1.35×ATR); activate=fee BE.

弱早强晚：ADX<20→70% 早激活；20–30→80%；>30→90% 晚激活。
"""

from __future__ import annotations

from app.core.breathing_stop import apply_breathing_tick, compute_initial_stop
from app.core.radar_trail import fee_cover_breakeven_stop
from app.core.trend_tier_params import (
    RADAR_ARM_ADX_STRONG,
    RADAR_ARM_ADX_WEAK,
    RADAR_ARM_MODE_ADX,
    RADAR_ARM_RATIO_MID,
    RADAR_ARM_RATIO_STRONG,
    RADAR_ARM_RATIO_WEAK,
    RADAR_ARM_TP1_ATR,
    radar_arm_absolute_trigger,
    radar_arm_ratio_by_adx,
    radar_arm_trigger_price,
)

ENTRY = 1900.0
ATR = 20.0
TP1 = ENTRY + RADAR_ARM_TP1_ATR * ATR  # 1927.0
TP2 = ENTRY + 2.70 * ATR


def test_adx_ratio_discrete_bands_weak_early_strong_late():
    # <20 → 70%, 20–30 → 80%, >30 → 90%
    assert radar_arm_ratio_by_adx(16.0) == RADAR_ARM_RATIO_WEAK
    assert radar_arm_ratio_by_adx(19.9) == RADAR_ARM_RATIO_WEAK
    assert radar_arm_ratio_by_adx(RADAR_ARM_ADX_WEAK) == RADAR_ARM_RATIO_MID
    assert radar_arm_ratio_by_adx(26.0) == RADAR_ARM_RATIO_MID
    assert radar_arm_ratio_by_adx(RADAR_ARM_ADX_STRONG) == RADAR_ARM_RATIO_MID
    assert radar_arm_ratio_by_adx(30.1) == RADAR_ARM_RATIO_STRONG
    assert radar_arm_ratio_by_adx(40.0) == RADAR_ARM_RATIO_STRONG
    assert abs(RADAR_ARM_RATIO_WEAK - 0.70) < 1e-9
    assert abs(RADAR_ARM_RATIO_MID - 0.80) < 1e-9
    assert abs(RADAR_ARM_RATIO_STRONG - 0.90) < 1e-9
    # Weak arms earlier (lower %); strong arms later (higher %)
    assert RADAR_ARM_RATIO_WEAK < RADAR_ARM_RATIO_MID < RADAR_ARM_RATIO_STRONG
    assert RADAR_ARM_MODE_ADX == "adx_70_80_90"


def test_absolute_mid_tp2_deprecated_returns_zero():
    assert radar_arm_absolute_trigger(TP1, TP2, is_reentry=False) == 0.0
    assert radar_arm_absolute_trigger(TP1, TP2, is_reentry=True) == 0.0


def test_trigger_uses_135_atr_times_adx_ratio():
    # ADX=17 → 70% → dist = 1.35*20*0.70
    trig = radar_arm_trigger_price(
        side="LONG", fill_entry=ENTRY, atr=ATR, adx=17.0, symbol="ETHUSDT",
    )
    assert abs(trig - (ENTRY + 1.35 * ATR * 0.70)) < 1e-9
    # ADX=35 → 90% (later arm)
    trig_s = radar_arm_trigger_price(
        side="LONG", fill_entry=ENTRY, atr=ATR, adx=35.0, symbol="ETHUSDT",
    )
    assert abs(trig_s - (ENTRY + 1.35 * ATR * 0.90)) < 1e-9
    assert trig_s > trig


def test_reentry_same_adx_arm_not_tp2():
    """Reentry no longer waits for TP2 — same ADX formula."""
    fill = ENTRY - 3.0
    trig = radar_arm_trigger_price(
        side="LONG", fill_entry=fill, atr=ATR, adx=17.0, is_reentry=True, symbol="ETHUSDT",
    )
    expect = fill + 1.35 * ATR * 0.70
    assert abs(trig - expect) < 1e-9
    assert abs(trig - TP2) > 1.0


def test_breathing_tick_arms_at_adx_ratio_fee_be():
    initial = compute_initial_stop(ENTRY, "LONG", ATR, symbol="ETHUSDT")
    arm_px = ENTRY + 1.35 * ATR * 0.70
    fee_be = fee_cover_breakeven_stop(ENTRY, "LONG", "ETHUSDT")
    # Below arm
    tick_wait = apply_breathing_tick(
        side="LONG",
        price=arm_px - 0.5,
        entry_price=ENTRY,
        initial_atr=ATR,
        initial_stop=initial,
        current_stop=initial,
        best_price=arm_px - 0.5,
        breakeven_phase=False,
        symbol="ETHUSDT",
        adx=17.0,
        radar_activated=False,
    )
    assert tick_wait["meta"].get("event") == "waiting_arm"
    assert tick_wait["meta"].get("radar_arm_mode") == RADAR_ARM_MODE_ADX
    # At arm → fee+tick BE (not entry+0.5ATR)
    tick = apply_breathing_tick(
        side="LONG",
        price=arm_px,
        entry_price=ENTRY,
        initial_atr=ATR,
        initial_stop=initial,
        current_stop=initial,
        best_price=arm_px,
        breakeven_phase=False,
        symbol="ETHUSDT",
        adx=17.0,
        radar_activated=False,
    )
    assert tick["meta"].get("radar_armed") is True
    assert tick["meta"].get("radar_arm_mode") == RADAR_ARM_MODE_ADX
    assert abs(float(tick["meta"].get("radar_arm_ratio") or 0) - 0.70) < 1e-9
    assert tick["meta"].get("activate_mode") == "fee_cover_be"
    assert float(tick["current_sl"]) >= fee_be - 1e-9
    assert float(tick["current_sl"]) < ENTRY + 0.5 * ATR - 1e-6


def test_tp1_early_fill_still_arms_residual():
    """TP1 already filled must NOT skip Layer-1 arm on residual."""
    initial = compute_initial_stop(ENTRY, "LONG", ATR, symbol="ETHUSDT")
    fee_be = fee_cover_breakeven_stop(ENTRY, "LONG", "ETHUSDT")
    px = TP1 + 1.0
    assert px > ENTRY + 1.35 * ATR * 0.70
    tick = apply_breathing_tick(
        side="LONG",
        price=px,
        entry_price=ENTRY,
        initial_atr=ATR,
        initial_stop=initial,
        current_stop=initial,
        best_price=px,
        breakeven_phase=False,
        symbol="ETHUSDT",
        adx=35.0,
        tp1_price=TP1,
        tp2_price=TP2,
        radar_activated=False,
    )
    assert tick["meta"].get("radar_armed") is True
    assert tick["meta"].get("radar_arm_mode") == RADAR_ARM_MODE_ADX
    assert float(tick["current_sl"]) >= fee_be - 1e-9


def test_layer2_trail_multiplier_unchanged():
    """Layer-2 trailDistanceMultiplier must stay ATR-ratio driven."""
    from app.core.breathing_profile import ETH_PROFILE, XAU_PROFILE, trail_distance_multiplier

    assert abs(trail_distance_multiplier(0.5, ETH_PROFILE) - 2.0) < 1e-9
    assert abs(trail_distance_multiplier(2.5, ETH_PROFILE) - 2.5) < 1e-9
    assert abs(trail_distance_multiplier(0.5, XAU_PROFILE) - 1.5) < 1e-9
    assert abs(trail_distance_multiplier(2.5, XAU_PROFILE) - 2.0) < 1e-9


def test_synthetic_path_smoke_eth_xau():
    """ADX arm activates to fee BE; never regresses below hard seed."""
    for sym, entry, atr, adx in (
        ("ETHUSDT", 2000.0, 25.0, 22.0),
        ("XAUUSDT", 3300.0, 12.0, 35.0),
    ):
        ratio = radar_arm_ratio_by_adx(adx)
        initial = compute_initial_stop(entry, "LONG", atr, symbol=sym)
        arm_px = entry + 1.35 * atr * ratio
        fee_be = fee_cover_breakeven_stop(entry, "LONG", sym)
        t0 = apply_breathing_tick(
            side="LONG", price=entry + 1.0, entry_price=entry, initial_atr=atr,
            initial_stop=initial, current_stop=initial, best_price=entry + 1.0,
            breakeven_phase=False, symbol=sym, adx=adx, radar_activated=False,
        )
        assert t0["meta"]["event"] == "waiting_arm"
        t1 = apply_breathing_tick(
            side="LONG", price=arm_px, entry_price=entry, initial_atr=atr,
            initial_stop=initial, current_stop=initial, best_price=arm_px,
            breakeven_phase=False, symbol=sym, adx=adx, radar_activated=False,
        )
        assert t1["meta"].get("radar_armed") is True
        assert float(t1["current_sl"]) >= fee_be - 1e-6
        assert float(t1["current_sl"]) >= float(initial) - 1e-9
        assert float(t1["current_sl"]) < entry + 0.5 * atr - 1e-6
