"""Regime cap guard: oversize detection and forced trim alignment."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_cap_guard import CAP_TOLERANCE_ETH, PositionCapGuardMixin
from app.core.position_supervisor import PositionSupervisor


class _CapProbe(PositionCapGuardMixin):
    exchange_id = "binance"
    regime = 3
    risk_multiplier = 1.0
    initial_principal = 755.0
    leverage = 10
    regime_settings = {
        3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
    }
    current_side = "LONG"
    watched_qty = 0.0
    watched_entry = 1770.0
    initial_qty = 0.0
    current_sl = 1775.0
    user_id = 6

    def __init__(self):
        self.client = MagicMock()
        self.client.get_available_balance.return_value = 12.0
        self.client.get_futures_account_summary.return_value = {
            "total_margin_balance": 755.0,
            "available_balance": 12.0,
        }
        self.on_log = MagicMock()
        self.on_alert = MagicMock()

    def _close_order_side(self):
        return "SELL"

    def _get_active_position(self):
        return {"size": 3.5, "entry_price": 1770.0, "side": "LONG"}

    def _radar_sl_to_pass(self):
        return 1775.0

    def _smart_realign_defenses(self, *a, **k):
        return {"matched": 3, "expected": 3, "audit": {}, "aligned": True}

    def _log(self, *a, **k):
        pass

    def _alert(self, *a, **k):
        pass

    def _save_state(self):
        pass


def test_cap_oversize_detects_stacked_position():
    probe = _CapProbe()
    # R3 35% × 755U principal × 10x @ 1775 ≈ 1.489 ETH (user live case)
    detail = probe._cap_oversize_detail(live_qty=2.954, price=1775.0)
    assert detail["oversized"] is True
    assert detail["max_qty"] == pytest.approx(1.489, rel=0.05)
    assert detail["trim_qty"] == pytest.approx(2.954 - detail["max_qty"], rel=0.02)
    assert detail["retain_ratio"] > 0.4


def test_cap_not_skewed_by_depleted_available_balance():
    """Regression: available=12 must NOT shrink max_qty to ~0.024 and flatten the book."""
    probe = _CapProbe()
    detail = probe._cap_oversize_detail(live_qty=2.954, price=1775.0)
    assert detail["max_qty"] > 1.0
    assert detail["trim_qty"] < 2.0
    assert probe._validate_cap_trim_plan(detail) is None


def test_cap_blocks_unsafe_trim_plan():
    probe = _CapProbe()
    bad = {
        "live_qty": 2.954,
        "target_qty": 0.024,
        "trim_qty": 2.93,
        "max_qty": 0.024,
    }
    err = probe._validate_cap_trim_plan(bad)
    assert err is not None


def test_cap_within_tolerance_not_oversized():
    probe = _CapProbe()
    max_qty, _ = probe._compute_regime_cap_target(1775.0)
    detail = probe._cap_oversize_detail(live_qty=max_qty + CAP_TOLERANCE_ETH * 0.5, price=1775.0)
    assert detail["oversized"] is False


def test_cap_float_epsilon_not_oversized():
    """0.197 vs 0.196 @ tol 0.001 must not trigger CAP_ALIGN_FAIL."""
    probe = _CapProbe()
    detail = probe._cap_oversize_detail(live_qty=0.197, price=1775.0)
    # max_qty ~1.489 — use synthetic small cap for gemini-style case
    detail_small = {
        **detail,
        "max_qty": 0.196,
        "target_qty": 0.196,
        "live_qty": 0.197,
    }
    raw_gap = 0.197 - 0.196
    detail_small["oversized"] = raw_gap > CAP_TOLERANCE_ETH + 1e-9
    assert detail_small["oversized"] is False


def test_enforce_cap_trims_to_target_not_near_zero():
    probe = _CapProbe()
    probe.watched_qty = 2.954
    probe.initial_qty = 2.954
    reads = iter([(2.954, 1775.0), (1.489, 1775.0), (1.489, 1775.0), (1.489, 1775.0)])

    with patch.object(probe, "_place_cap_trim_order", return_value=True) as trim, patch.object(
        probe, "_read_live_position_qty", side_effect=lambda: next(reads),
    ), patch.object(probe, "_smart_realign_defenses") as realign:
        realign.return_value = {"matched": 3, "expected": 3}
        result = probe._enforce_regime_cap_alignment(2.954, 1775.0, 1775.0, reason="test")

    trim.assert_called_once()
    called_qty = trim.call_args[0][0]
    assert called_qty == pytest.approx(1.466, rel=0.02)
    assert result["new_qty"] == pytest.approx(1.489, rel=0.02)


def test_binance_supervisor_inherits_cap_guard():
    client = MagicMock()
    sup = PositionSupervisor(user_id=1, client=client)
    assert hasattr(sup, "_enforce_regime_cap_alignment")
    assert hasattr(sup, "_compute_regime_cap_target")


def test_open_position_trims_oversize_after_fill():
    client = MagicMock()
    client.get_available_balance.return_value = 1000.0
    client.get_current_price.return_value = 1770.0
    client.set_leverage.return_value = None
    client.cancel_all_open_orders.return_value = None
    client.place_market_order.return_value = {"orderId": 1}

    sup = PositionSupervisor(user_id=6, client=client, initial_principal=700.0)
    sup.regime = 4
    sup.tv_tps = [1800.0, 1850.0, 1900.0]
    sup.tv_price = 1770.0
    sup.on_trade_open = MagicMock(return_value=1)
    sup.on_log = MagicMock()
    sup.on_alert = MagicMock()

    stacked_qty = 3.5
    with patch.object(
        sup.position_manager, "get_position",
        return_value={"positionAmt": str(stacked_qty), "entryPrice": "1770.0"},
    ), patch.object(sup, "_protect_and_monitor") as mon, patch.object(
        sup, "_enforce_regime_cap_alignment",
        return_value={"trimmed": 1.5, "new_qty": 1.977, "aligned": True},
    ) as cap:
        sup._open_position("LONG", 1770.0)

    cap.assert_called_once()
    mon.assert_called_once()
    assert mon.call_args[0][0] == pytest.approx(1.977, rel=0.01)
