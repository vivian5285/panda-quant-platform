"""Regime cap guard: oversize detection and forced trim alignment."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.position_cap_guard import CAP_TOLERANCE_ETH, PositionCapGuardMixin
from app.core.position_qty_tolerance import CAP_EXCESS_RATIO, qty_change_significant
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


def test_cap_ignores_minor_price_drift():
    """Regression: 1.365 vs 1.363 ETH (~0.15%) must not trigger cap trim / TP realign."""
    probe = _CapProbe()
    meta = {"regime": 3, "margin_pct": 0.35, "initial_principal": 755.0}
    with patch.object(probe, "_compute_regime_cap_target", return_value=(1.363, meta)):
        detail = probe._cap_oversize_detail(live_qty=1.365, price=1774.14)
    assert detail["oversized"] is False
    assert detail["trim_qty"] == 0.0
    assert detail["tolerance"] >= 1.365 * CAP_EXCESS_RATIO * 0.5


def test_cap_ignores_small_account_three_pct_overshoot():
    """Regression: 0.2010 vs 0.1950 (~3%) must NOT trigger CAP_ALIGN trim."""
    probe = _CapProbe()
    probe.initial_principal = 99.91
    probe.client.get_futures_account_summary.return_value = {
        "total_margin_balance": 97.89,
        "available_balance": 50.0,
    }
    meta = {"regime": 3, "margin_pct": 0.35, "initial_principal": 99.91, "equity_balance": 97.89}
    with patch.object(probe, "_compute_regime_cap_target", return_value=(0.1950, meta)):
        detail = probe._cap_oversize_detail(live_qty=0.2010, price=1774.0)
    assert detail["oversized"] is False
    assert detail["trim_qty"] == 0.0
    assert 0.2010 - 0.1950 < detail["tolerance"]


def test_cap_triggers_on_material_overshoot():
    """~50% over cap must still trigger trim."""
    probe = _CapProbe()
    meta = {"regime": 3, "margin_pct": 0.35, "initial_principal": 755.0}
    with patch.object(probe, "_compute_regime_cap_target", return_value=(0.195, meta)):
        detail = probe._cap_oversize_detail(live_qty=0.350, price=1774.0)
    assert detail["oversized"] is True
    assert detail["trim_qty"] > 0


def test_cap_float_epsilon_not_oversized():
    """0.197 vs 0.196 within drift band must not trigger CAP_ALIGN."""
    probe = _CapProbe()
    detail = probe._cap_oversize_detail(live_qty=0.197, price=1775.0)
    tol = probe._cap_excess_tolerance(0.197, 0.196)
    assert 0.197 - 0.196 <= tol
    assert detail["oversized"] is False or (0.197 - detail["max_qty"]) <= tol


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
    client.configure_mock(exchange_id="binance", trading_symbol="ETHUSDT", trading_leverage=25)
    sup = PositionSupervisor(user_id=1, client=client)
    assert hasattr(sup, "_enforce_regime_cap_alignment")
    assert hasattr(sup, "_compute_regime_cap_target")
    assert sup.exchange_id == "binance"


class _DeepcoinCapProbe(PositionCapGuardMixin):
    exchange_id = "deepcoin"
    regime = 3
    risk_multiplier = 1.0
    initial_principal = 700.0
    leverage = 10
    face_value = 0.1
    regime_settings = {
        3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
    }
    current_side = "LONG"
    watched_qty = 0
    watched_entry = 3000.0
    initial_qty = 0
    current_sl = 3000.0
    user_id = 1
    symbol = "ETH-USDT-SWAP"

    def __init__(self):
        self.client = MagicMock()
        self.client.get_futures_account_summary.return_value = {
            "total_margin_balance": 700.0,
            "available_balance": 15.0,
        }
        self.on_log = MagicMock()
        self.on_alert = MagicMock()

    def _close_order_side(self):
        return "sell"

    def _safe_qty(self, v):
        return int(v)

    def _get_active_position(self):
        return {"size": 15, "entry_price": 3000.0, "posSide": "long"}

    def _radar_sl_to_pass(self):
        return 3000.0

    def _smart_realign_defenses(self, *a, **k):
        return {"matched": 3, "expected": 3, "audit": {}, "aligned": True}

    def _log(self, *a, **k):
        pass

    def _alert(self, *a, **k):
        pass

    def _save_state(self):
        pass


def test_deepcoin_cap_oversize_uses_principal_not_available():
    """Regression: avail=15 must NOT shrink max contracts when equity=700."""
    probe = _DeepcoinCapProbe()
    detail = probe._cap_oversize_detail(live_qty=15, price=3000.0)
    # 700 × 35% × 10 / (3000 × 0.1) ≈ 8 张
    assert detail["oversized"] is True
    assert detail["max_qty"] == 8
    assert detail["trim_qty"] == 7
    assert probe._validate_cap_trim_plan(detail) is None


def test_deepcoin_enforce_cap_trims_to_target_not_near_zero():
    probe = _DeepcoinCapProbe()
    probe.watched_qty = 15
    probe.initial_qty = 15
    reads = iter([(15, 3000.0), (8, 3000.0), (8, 3000.0), (8, 3000.0)])

    with patch.object(probe, "_place_cap_trim_order", return_value=True) as trim, patch.object(
        probe, "_read_live_position_qty", side_effect=lambda: next(reads),
    ), patch.object(probe, "_smart_realign_defenses") as realign:
        realign.return_value = {"matched": 3, "expected": 3}
        result = probe._enforce_regime_cap_alignment(15, 3000.0, 3000.0, reason="test")

    trim.assert_called_once()
    assert trim.call_args[0][0] == 7
    assert result["new_qty"] == 8


def test_deepcoin_supervisor_inherits_cap_guard():
    from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor

    client = MagicMock()
    sup = DeepcoinPositionSupervisor(user_id=1, client=client)
    assert hasattr(sup, "_enforce_regime_cap_alignment")
    assert hasattr(sup, "_compute_regime_cap_target")
    assert sup.exchange_id == "deepcoin"


def test_okx_cap_uses_principal_not_available():
    probe = _CapProbe()
    probe.exchange_id = "okx"
    probe.client.get_futures_account_summary.return_value = {
        "total_margin_balance": 755.0,
        "available_balance": 12.0,
    }
    detail = probe._cap_oversize_detail(live_qty=2.954, price=1775.0)
    assert detail["oversized"] is True
    assert detail["max_qty"] > 1.0
    assert detail["sizing_base"] == 755.0


def test_gate_cap_uses_principal_not_available():
    probe = _CapProbe()
    probe.exchange_id = "gate"
    probe.initial_principal = 700.0
    probe.client.get_futures_account_summary.return_value = {
        "total_margin_balance": 700.0,
        "available_balance": 12.0,
    }
    detail = probe._cap_oversize_detail(live_qty=2.954, price=1775.0)
    assert detail["max_qty"] == pytest.approx(1.385, rel=0.05)
    assert probe._validate_cap_trim_plan(detail) is None


def test_open_position_skips_cap_trim_after_fill():
    """User rule: flat OPEN must not instantly CAP-trim (ant residue)."""
    client = MagicMock()
    client.configure_mock(exchange_id="binance", trading_symbol="ETHUSDT", trading_leverage=25)
    client.get_futures_account_summary.return_value = {"total_margin_balance": 1000.0}
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
    ) as cap:
        sup._open_position("LONG", 1770.0)

    cap.assert_not_called()
    mon.assert_called_once()
    assert mon.call_args[0][0] == pytest.approx(stacked_qty, rel=0.01)
