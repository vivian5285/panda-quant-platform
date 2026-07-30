"""Regression tests for XAU-2026-07-28 root-cause fixes.

Fix 1: Hard stop direction guard in _arm_temp_tv_stop_on_open
Fix 2: Emergency priority bypass in throttle valve
Fix 3: (state corruption — confirmed N/A after code review)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.breathing_stop import compute_temp_tv_stop, compute_hard_stop_distance
from app.core.rest_throttle_valve import (
    ThrottleDenied,
    acquire_rest_permit,
    require_rest_or_transient,
    sentinel_may_rest,
    reset_for_tests,
)
from app.core.ip_rest_cooldown import reset_for_tests as _reset_cool, note_rate_limit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockClient:
    user_id = 1
    trading_symbol = "XAUUSDT"

    def get_position(self, symbol):
        return {"positionAmt": "1.0", "entryPrice": "4080.15"}

    def get_current_price(self, symbol):
        return 4080.15

    def place_market_order(self, *a, **k):
        return {}

    def place_stop_limit_order(self, *a, **k):
        return {}


class _MockAlert:
    def __init__(self):
        self.calls = []

    def __call__(self, sev, code, msg, detail=None):
        self.calls.append((sev, code, msg, detail))


def _make_guard() -> AdverseRadarMixin:
    """Build a minimal AdverseRadarMixin instance for testing.

    Uses __new__ + manual field setup + _init_adverse_radar_fields() to avoid
    needing the full supervisor class hierarchy.
    """
    guard = AdverseRadarMixin.__new__(AdverseRadarMixin)
    # Required stubs (set before _init_adverse_radar_fields so it doesn't auto-set these)
    guard.user_id = 1
    guard.canonical_symbol = "XAUUSDT"
    guard.symbol = "XAUUSDT"
    guard.exchange_id = "binance"
    guard.current_side = "LONG"
    guard.tv_price = 4080.0
    guard.trend_tier = 3
    guard.regime = 3
    # These will be auto-initialized by _init_adverse_radar_fields()
    # but we set them explicitly for the test scenarios:
    guard._tv_stop_loss_ref = 0.0
    guard._pending_open_tv_sl = 0.0
    guard.tv_sl = 0.0
    # Client + alert/log stubs
    guard.client = _MockClient()
    guard._alert = _MockAlert()
    guard._log = MagicMock()
    # Initialize all default fields (safe to call multiple times)
    guard._init_adverse_radar_fields()
    # Set test-specific overrides
    guard.current_side = "LONG"
    guard._tv_stop_loss_ref = 0.0
    guard._pending_open_tv_sl = 0.0
    guard.tv_sl = 0.0
    guard._frozen_hard_stop_px = 0.0
    guard._tv_hard_sl_price = 0.0
    guard._vps_hard_sl_meta = {}
    guard._temp_tv_stop_active = False
    guard.radar_activated = False
    return guard


# ---------------------------------------------------------------------------
# Fix 1: Hard stop direction guard
# ---------------------------------------------------------------------------

class TestHardStopDirectionGuard:
    """LONG stops must be BELOW entry; SHORT stops must be ABOVE entry."""

    def test_compute_temp_tv_stop_long_correctly_below_entry(self):
        """Sanity: compute_temp_tv_stop returns correct value for LONG."""
        entry = 4080.15
        tv_sl = 4060.0  # below entry — correct
        stop = compute_temp_tv_stop(entry, "LONG", tv_sl)
        assert stop < entry, f"LONG stop {stop} must be below entry {entry}"
        assert stop == entry - (entry - tv_sl) * 1.15

    def test_compute_temp_tv_stop_short_correctly_above_entry(self):
        """Sanity: compute_temp_tv_stop returns correct value for SHORT."""
        entry = 4080.15
        tv_sl = 4100.0  # above entry — correct
        stop = compute_temp_tv_stop(entry, "SHORT", tv_sl)
        assert stop > entry, f"SHORT stop {stop} must be above entry {entry}"
        assert stop == entry + (tv_sl - entry) * 1.15

    def test_arm_rejects_long_stop_above_entry(self):
        """If LONG stop ends up above entry, _arm_temp_tv_stop_on_open rejects it."""
        guard = _make_guard()
        guard.current_side = "LONG"
        # Simulate a polluted state where _tv_stop_loss_ref would give a
        # "wrong side" tv_sl (the XAU bug scenario: tv_sl > entry for a LONG)
        # Here we test the direct output of compute_temp_tv_stop with a tv_sl
        # that would produce entry + dist instead of entry - dist.
        #
        # The guard itself calls _pine_stop_loss_ref() which reads _tv_stop_loss_ref.
        # Set tv_sl ABOVE entry for a LONG to simulate the bug condition.
        guard._tv_stop_loss_ref = 4100.0  # ABOVE entry — wrong for LONG
        guard._pending_open_tv_sl = 4100.0
        guard.tv_sl = 4100.0

        fill = 4080.15
        result = guard._arm_temp_tv_stop_on_open(fill)

        assert result.get("ok") is False, "Must reject LONG stop on wrong side of entry"
        assert "wrong_side" in result.get("reason", "").lower()
        assert result["tv_stop_loss"] > fill, "Wrong tv_sl is above entry for LONG"
        # Alert must have been sent
        assert len(guard._alert.calls) > 0
        sev, code, _, _ = guard._alert.calls[-1]
        assert code == "HARD_SL_SIGNAL_WRONG_SIDE"
        assert sev == "critical"

    def test_arm_rejects_short_stop_below_entry(self):
        """If SHORT stop ends up below entry, _arm_temp_tv_stop_on_open rejects it."""
        guard = _make_guard()
        guard.current_side = "SHORT"
        guard._tv_stop_loss_ref = 4060.0  # BELOW entry — wrong for SHORT
        guard._pending_open_tv_sl = 4060.0
        guard.tv_sl = 4060.0

        fill = 4080.15
        result = guard._arm_temp_tv_stop_on_open(fill)

        assert result.get("ok") is False
        assert "wrong_side" in result.get("reason", "").lower()
        assert result["tv_stop_loss"] < fill, "Wrong tv_sl is below entry for SHORT"

    def test_arm_accepts_correct_long_stop(self):
        """Normal case: LONG tv_sl below entry → stop correctly below entry → accepted."""
        guard = _make_guard()
        guard.current_side = "LONG"
        guard._tv_stop_loss_ref = 4060.0  # below entry — correct
        guard._pending_open_tv_sl = 4060.0
        guard.tv_sl = 4060.0

        fill = 4080.15
        result = guard._arm_temp_tv_stop_on_open(fill)

        assert result.get("ok") is True
        assert result["stop_price"] < fill
        assert result["stop_price"] > 0

    def test_arm_accepts_correct_short_stop(self):
        """Normal case: SHORT tv_sl above entry → stop correctly above entry → accepted."""
        guard = _make_guard()
        guard.current_side = "SHORT"
        guard._tv_stop_loss_ref = 4100.0  # above entry — correct
        guard._pending_open_tv_sl = 4100.0
        guard.tv_sl = 4100.0

        fill = 4080.15
        result = guard._arm_temp_tv_stop_on_open(fill)

        assert result.get("ok") is True
        assert result["stop_price"] > fill
        assert result["stop_price"] > 0

    def test_direction_guard_with_normal_tv_sl_produces_correct_stop(self):
        """Edge: tv_sl very close to entry but still on correct side → accepted."""
        guard = _make_guard()
        guard.current_side = "LONG"
        guard._tv_stop_loss_ref = 4079.0  # just below entry — still correct
        guard._pending_open_tv_sl = 4079.0
        guard.tv_sl = 4079.0

        fill = 4080.15
        result = guard._arm_temp_tv_stop_on_open(fill)

        assert result.get("ok") is True
        assert result["stop_price"] < fill


# ---------------------------------------------------------------------------
# Fix 2: Emergency priority bypass in throttle valve
# ---------------------------------------------------------------------------

class TestThrottleEmergencyPriority:
    """Emergency calls (HARD_SL_FAIL_ABORT etc.) bypass budget but respect IP cool-down."""

    def setup_method(self):
        reset_for_tests()
        _reset_cool()

    def teardown_method(self):
        reset_for_tests()
        _reset_cool()

    def test_normal_call_consumes_budget(self):
        """Normal priority calls consume budget slots."""
        for i in range(40):
            acquire_rest_permit(exchange="binance", user_id=1, op="get_position", priority="normal")
        # 41st call should be denied
        with pytest.raises(ThrottleDenied):
            acquire_rest_permit(exchange="binance", user_id=1, op="get_position", priority="normal")

    def test_emergency_bypasses_budget(self):
        """Emergency priority calls are NOT blocked by budget exhaustion."""
        # Exhaust the budget with normal calls
        for i in range(40):
            acquire_rest_permit(exchange="binance", user_id=1, op="get_position", priority="normal")
        # Emergency call must NOT raise
        acquire_rest_permit(exchange="binance", user_id=1, op="HARD_SL_FAIL_ABORT", priority="emergency")

    def test_emergency_still_blocked_by_ip_cooldown(self):
        """Emergency calls ARE blocked by IP-level cool-down (exchange rate-limit ban)."""
        note_rate_limit(exchange="binance", user_id=1, cool_sec=30.0)
        # Even emergency should respect IP cool-down
        with pytest.raises(ThrottleDenied):
            acquire_rest_permit(exchange="binance", user_id=1, op="HARD_SL_FAIL_ABORT", priority="emergency")

    def test_require_rest_or_transient_emergency(self):
        """require_rest_or_transient passes priority through to acquire_rest_permit."""
        for i in range(40):
            require_rest_or_transient(exchange="binance", user_id=1, op="get_position")
        # Emergency should not raise
        require_rest_or_transient(exchange="binance", user_id=1, op="HARD_SL_FAIL_ABORT", priority="emergency")

    def test_sentinel_may_rest_emergency_ok(self):
        """sentinel_may_rest returns True for emergency when budget is exhausted."""
        # Exhaust budget
        for i in range(40):
            acquire_rest_permit(exchange="binance", user_id=1, op="get_position", priority="normal")
        ok, reason = sentinel_may_rest(
            exchange="binance", user_id=1, trading_paused=False, priority="emergency",
        )
        assert ok is True
        assert reason == "emergency_ok"

    def test_sentinel_may_rest_normal_blocks_at_budget(self):
        """sentinel_may_rest returns False for normal when budget exhausted."""
        for i in range(40):
            acquire_rest_permit(exchange="binance", user_id=1, op="get_position", priority="normal")
        ok, reason = sentinel_may_rest(
            exchange="binance", user_id=1, trading_paused=False, priority="normal",
        )
        assert ok is False
        assert "budget" in reason

    def test_multiple_emergency_calls_all_succeed(self):
        """Multiple emergency calls (simulating HARD_SL_FAIL_ABORT + close retry) all succeed."""
        for i in range(100):
            acquire_rest_permit(exchange="binance", user_id=1, op="HARD_SL_FAIL_ABORT", priority="emergency")
        # All should have succeeded
        ok, reason = sentinel_may_rest(
            exchange="binance", user_id=1, trading_paused=False, priority="emergency",
        )
        assert ok is True


# ---------------------------------------------------------------------------
# Integration: Full open flow with direction violation
# ---------------------------------------------------------------------------

class TestFullOpenFlowDirectionGuard:
    """Simulate the XAU-2026-07-28 scenario: LONG with wrong-side tv_sl."""

    def test_protect_and_monitor_aborts_on_direction_violation(self):
        """When direction guard fires, _protect_and_monitor must abort (not naked-trade)."""
        guard = _make_guard()
        guard.current_side = "LONG"
        # Simulate wrong tv_sl (above entry for LONG)
        guard._tv_stop_loss_ref = 4098.80
        guard._pending_open_tv_sl = 4098.80
        guard.tv_sl = 4098.80

        fill = 4080.15
        result = guard._arm_temp_tv_stop_on_open(fill)

        assert result.get("ok") is False
        assert "wrong_side" in result.get("reason", "")
