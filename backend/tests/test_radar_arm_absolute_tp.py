"""Gemini §6.1: first arm=(TP1+TP2)/2, reentry arm=TP2 — shared absolute TPs."""

from __future__ import annotations

from app.core.breathing_stop import apply_breathing_tick, compute_initial_stop
from app.core.trend_tier_params import (
    radar_arm_absolute_trigger,
    radar_arm_trigger_price,
    radar_armed_by_price,
)

# Spec numerical example (LONG)
TP1 = 1925.65
TP2 = 1955.00
MID = (TP1 + TP2) / 2.0  # 1940.325
ENTRY = 1900.0
ATR = 20.0


def test_absolute_trigger_first_is_midpoint():
    assert abs(radar_arm_absolute_trigger(TP1, TP2, is_reentry=False) - MID) < 1e-9


def test_absolute_trigger_reentry_is_tp2():
    assert abs(radar_arm_absolute_trigger(TP1, TP2, is_reentry=True) - TP2) < 1e-9


def test_first_open_arms_at_midpoint_not_tp1_path():
    """First open: arm at mid; price between old 0.85·tp1_dist and mid stays unarmed."""
    # Old formula would arm at fill + 0.85*|tp1−tv| ≈ 1900 + 0.85*25.65 ≈ 1921.8
    old_style = ENTRY + 0.85 * (TP1 - ENTRY)
    assert old_style < MID
    assert radar_armed_by_price(
        side="LONG", price=old_style, fill_entry=ENTRY, tp1=TP1, tp2=TP2, is_reentry=False,
    ) is False
    assert radar_armed_by_price(
        side="LONG", price=MID, fill_entry=ENTRY, tp1=TP1, tp2=TP2, is_reentry=False,
    ) is True


def test_reentry_past_midpoint_before_tp2_radar_stays_off():
    """CRITICAL: reentry shares TP1/TP2 absolutes; past mid but < TP2 → NOT armed.

    Easy miss: reuse first-open midpoint threshold for reentry.
    """
    px = MID + 5.0  # past midpoint, still before TP2
    assert MID < px < TP2
    trig = radar_arm_trigger_price(
        side="LONG", fill_entry=ENTRY - 3.0, tp1=TP1, tp2=TP2, is_reentry=True,
    )
    assert abs(trig - TP2) < 1e-9
    assert radar_armed_by_price(
        side="LONG", price=px, fill_entry=ENTRY - 3.0, tp1=TP1, tp2=TP2, is_reentry=True,
    ) is False
    # Same price WOULD arm on first open
    assert radar_armed_by_price(
        side="LONG", price=px, fill_entry=ENTRY, tp1=TP1, tp2=TP2, is_reentry=False,
    ) is True


def test_reentry_arms_only_at_tp2():
    assert radar_armed_by_price(
        side="LONG", price=TP2 - 0.01, fill_entry=ENTRY, tp1=TP1, tp2=TP2, is_reentry=True,
    ) is False
    assert radar_armed_by_price(
        side="LONG", price=TP2, fill_entry=ENTRY, tp1=TP1, tp2=TP2, is_reentry=True,
    ) is True


def test_breathing_tick_reentry_mid_zone_keeps_initial_stop():
    """apply_breathing_tick must not lift SL while reentry price is mid→TP2 gap."""
    entry = ENTRY - 2.0  # better reentry fill
    initial = compute_initial_stop(entry, "LONG", ATR, symbol="ETHUSDT")
    px = MID + 4.0
    assert MID < px < TP2
    tick = apply_breathing_tick(
        side="LONG",
        price=px,
        entry_price=entry,
        initial_atr=ATR,
        initial_stop=initial,
        current_stop=initial,
        best_price=px,
        breakeven_phase=False,
        symbol="ETHUSDT",
        tp1_price=TP1,
        tp2_price=TP2,
        is_reentry=True,
        radar_activated=False,
    )
    assert tick["meta"].get("radar_armed") is False
    assert tick["meta"].get("event") == "waiting_arm"
    assert tick["meta"].get("radar_arm_mode") == "tp2"
    assert abs(float(tick["current_sl"]) - float(initial)) < 1e-9
    assert float(tick["current_sl"]) < entry  # still below entry — not activate lift


def test_breathing_tick_first_open_arms_at_mid_and_lifts():
    initial = compute_initial_stop(ENTRY, "LONG", ATR, symbol="ETHUSDT")
    tick = apply_breathing_tick(
        side="LONG",
        price=MID,
        entry_price=ENTRY,
        initial_atr=ATR,
        initial_stop=initial,
        current_stop=initial,
        best_price=MID,
        breakeven_phase=False,
        symbol="ETHUSDT",
        tp1_price=TP1,
        tp2_price=TP2,
        is_reentry=False,
        radar_activated=False,
    )
    assert tick["meta"].get("radar_armed") is True
    assert tick["meta"].get("radar_arm_mode") == "tp1_tp2_mid"
    assert float(tick["current_sl"]) >= ENTRY + 0.5 * ATR - 1e-9


def test_short_reentry_mid_zone():
    tp1, tp2 = 1874.35, 1845.0
    mid = (tp1 + tp2) / 2.0
    px = mid - 5.0  # past mid toward TP2 for SHORT, but not at TP2 yet
    assert tp2 < px < mid
    assert radar_armed_by_price(
        side="SHORT", price=px, fill_entry=1900.0, tp1=tp1, tp2=tp2, is_reentry=True,
    ) is False
    assert radar_armed_by_price(
        side="SHORT", price=tp2, fill_entry=1900.0, tp1=tp1, tp2=tp2, is_reentry=True,
    ) is True
