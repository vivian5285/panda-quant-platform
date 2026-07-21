"""Cap guard: RISK20 detect-only (no autonomous trim orders)."""

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
    base_qty = 0.0
    current_sl = 1775.0
    tv_sl = 1755.0
    user_id = 6
    canonical_symbol = "ETHUSDT"
    _tv_entry_fields = {
        "risk_pct": 2.03,
        "leverage": 10,
        "qty_ratio": 1.0,
        "regime": 3,
        "qty_ratio_source": "tv_qty_ratio",
    }

    def __init__(self):
        self.client = MagicMock()
        self.client.get_available_balance.return_value = 12.0
        self.client.get_futures_account_summary.return_value = {
            "total_margin_balance": 755.0,
            "available_balance": 12.0,
        }
        self.on_log = MagicMock()
        self.on_alert = MagicMock()

    def _round_qty(self, q):
        return float(int(float(q) * 1000) / 1000)

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
    # RISK20: notional 755*5/1775 ? 2.126 binds vs risk 151/20=7.55
    detail = probe._cap_oversize_detail(live_qty=2.954, price=1775.0)
    assert detail["oversized"] is True
    assert detail["cap_source"] == "risk20_cap5x"
    assert detail["max_qty"] == pytest.approx(2.126, abs=0.01)
    assert detail["trim_qty"] == pytest.approx(2.954 - detail["max_qty"], rel=0.02)


def test_cap_not_skewed_by_depleted_available_balance():
    probe = _CapProbe()
    detail = probe._cap_oversize_detail(live_qty=2.954, price=1775.0)
    assert detail["max_qty"] == pytest.approx(2.126, abs=0.01)
    assert detail["cap_source"] == "risk20_cap5x"


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
    probe = _CapProbe()
    meta = {"regime": 3, "initial_principal": 755.0, "cap_source": "risk20_cap5x"}
    with patch.object(probe, "_compute_regime_cap_target", return_value=(1.363, meta)):
        detail = probe._cap_oversize_detail(live_qty=1.365, price=1775.0)
    assert detail["oversized"] is False


def test_cap_drift_band_small_excess():
    probe = _CapProbe()
    meta = {"regime": 3, "initial_principal": 99.91, "equity_balance": 97.89}
    with patch.object(probe, "_compute_regime_cap_target", return_value=(0.1950, meta)):
        detail = probe._cap_oversize_detail(live_qty=0.2010, price=1775.0)
    assert detail["oversized"] is False


def test_cap_tracks_intentional_qty_after_add():
    probe = _CapProbe()
    probe.initial_qty = 1.5
    probe.base_qty = 1.0
    max_qty, meta = probe._compute_regime_cap_target(1775.0)
    assert meta["cap_source"] == "risk20_cap5x"
    assert max_qty >= 1.5


def test_cap_enforce_trim_is_detect_only(monkeypatch):
    probe = _CapProbe()
    probe._in_open_cap_grace = MagicMock(return_value=False)
    placed = []
    probe._place_cap_trim_order = lambda trim_qty: placed.append(trim_qty) or True
    result = probe._enforce_regime_cap_alignment(2.954, 1775.0, 1775.0, reason="test")
    assert placed == []
    assert result.get("detect_only") is True
    assert result.get("trimmed") == 0.0
    assert result.get("aligned") is False


def test_supervisor_has_cap_methods():
    client = MagicMock()
    client.configure_mock(exchange_id="binance", trading_symbol="ETHUSDT", trading_leverage=25)
    sup = PositionSupervisor(user_id=1, client=client, initial_principal=1000.0)
    assert hasattr(sup, "_enforce_regime_cap_alignment")
    assert hasattr(sup, "_compute_regime_cap_target")


def test_qty_change_significant_helper():
    assert qty_change_significant(1.0, 1.0 + CAP_EXCESS_RATIO * 0.5, is_contracts=False) is False
    assert qty_change_significant(1.0, 1.2, is_contracts=False) is True


def test_bind_tv_leverage_sets_client_and_supervisor():
    client = MagicMock()
    client.configure_mock(exchange_id="binance", trading_symbol="ETHUSDT", trading_leverage=25)
    client.set_leverage = MagicMock(return_value={})
    sup = PositionSupervisor(user_id=1, client=client, initial_principal=1000.0)
    sup._apply_tv_entry_context({
        "entry_type": "OPEN",
        "risk_pct": 2.4,
        "leverage": 5,
        "qty_ratio": 1.0,
        "regime": 2,
    })
    lev = sup._bind_tv_leverage()
    assert lev == 5
    assert sup.leverage == 5
    assert client.trading_leverage == 5
    client.set_leverage.assert_called_with(sup.symbol, leverage=5)


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
    base_qty = 0
    current_sl = 3000.0
    tv_sl = 2970.0
    user_id = 1
    symbol = "ETH-USDT-SWAP"
    canonical_symbol = "ETHUSDT"
    _tv_entry_fields = {
        "risk_pct": 2.03,
        "leverage": 10,
        "qty_ratio": 1.0,
        "regime": 3,
        "qty_ratio_source": "tv_qty_ratio",
    }

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


def test_deepcoin_cap_oversize_uses_risk20_not_available():
    probe = _DeepcoinCapProbe()
    detail = probe._cap_oversize_detail(live_qty=15, price=3000.0)
    # notional binds eth?1.166 ? 11 contracts
    assert detail["oversized"] is True
    assert detail["cap_source"] == "risk20_cap5x"
    assert detail["max_qty"] == pytest.approx(11, abs=1)
    assert detail["max_qty"] < detail["live_qty"]


def test_deepcoin_supervisor_inherits_cap_guard():
    from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor

    client = MagicMock()
    client.trading_leverage = 25
    with patch.object(DeepcoinPositionSupervisor, "_start_idle_flat_patrol"), patch.object(
        DeepcoinPositionSupervisor, "_start_signal_worker"
    ):
        sup = DeepcoinPositionSupervisor(user_id=1, client=client)
    assert hasattr(sup, "_enforce_regime_cap_alignment")
    assert hasattr(sup, "_compute_regime_cap_target")
    assert hasattr(sup, "_bind_tv_leverage")
    assert sup.exchange_id == "deepcoin"


def test_okx_cap_uses_risk20():
    probe = _CapProbe()
    probe.exchange_id = "okx"
    probe.client.get_futures_account_summary.return_value = {
        "total_margin_balance": 755.0,
        "available_balance": 12.0,
    }
    detail = probe._cap_oversize_detail(live_qty=2.954, price=1775.0)
    assert detail["oversized"] is True
    assert detail["cap_source"] == "risk20_cap5x"
    assert detail["sizing_base"] == 755.0


def test_gate_cap_uses_risk20():
    probe = _CapProbe()
    probe.exchange_id = "gate"
    probe.initial_principal = 700.0
    probe.client.get_futures_account_summary.return_value = {
        "total_margin_balance": 700.0,
        "available_balance": 12.0,
    }
    detail = probe._cap_oversize_detail(live_qty=2.954, price=1775.0)
    assert detail["oversized"] is True
    assert detail["cap_source"] == "risk20_cap5x"


def test_open_position_skips_cap_trim_after_fill():
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
    sup.tv_sl = 1740.0
    sup._apply_tv_entry_context({
        "entry_type": "OPEN", "risk_pct": 2.4, "leverage": 5, "qty_ratio": 1.0, "regime": 4,
        "qty": 1.0,
    })
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
        mon.return_value = {}
        sup._open_position("LONG", 1770.0)

    cap.assert_not_called()
    mon.assert_called_once()
    assert mon.call_args[0][0] == pytest.approx(stacked_qty, rel=0.01)
    client.set_leverage.assert_called()
    assert sup.leverage == 5
