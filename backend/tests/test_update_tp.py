"""TV v6.9.108 UPDATE_TP — momentum TP upgrade (TP-only, never touch SL/radar)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.adverse_radar_guard import AdverseRadarMixin


class _FakeSup(AdverseRadarMixin):
    def __init__(self, *, exchange_id="binance"):
        self.exchange_id = exchange_id
        self.user_id = 1
        self.symbol = "ETHUSDT"
        self.tv_tps = [1800.0, 1850.0, 1900.0]
        self.tv_sl = 1700.0
        self.current_sl = 1720.0
        self.current_side = "LONG"
        self.watched_qty = 1.0
        self.watched_entry = 1750.0
        self.regime = 3
        self.current_atr = 25.0
        self.current_trade_id = None
        self.logs = []
        self.alerts = []
        self._pos = {"size": 1.0, "entry_price": 1750.0, "side": "LONG"}
        self._cancelled = 0
        self._placed = 0
        self._mark = 1850.0
        self.client = MagicMock()
        self.on_trade_update_targets = MagicMock()

    def _log(self, event_type, message, detail=None):
        self.logs.append((event_type, message, detail))

    def _alert(self, severity, alert_type, title, message, detail=None):
        self.alerts.append((severity, alert_type, title, message, detail))

    def _get_active_position(self):
        return self._pos

    def _defense_mark_price(self):
        return self._mark

    def _cancel_all_tp_limit_orders(self, *, flat_purge=False):
        self._cancelled += 1
        return 3

    def _rebuild_tp_limit_orders(self, qty, entry, dynamic_sl=None):
        assert dynamic_sl is None  # must never pass SL into TP rebuild
        self._placed += 1
        return 3

    def _rebuild_defenses(self, qty, entry, dynamic_sl=None):
        assert dynamic_sl is None
        self._placed += 1
        return 3

    def _save_state(self):
        pass


def _payload(**over):
    base = {
        "action": "UPDATE_TP",
        "side": "LONG",
        "tv_tp1": 1900.50,
        "tv_tp2": 1930.00,
        "tv_tp3": 1970.00,
    }
    base.update(over)
    return base


def test_update_tp_replaces_tps_only():
    sup = _FakeSup()
    hard_before = sup.tv_sl
    radar_before = sup.current_sl
    out = sup._handle_update_tp(_payload())
    assert out["status"] == "ok"
    assert sup.tv_tps == [1900.5, 1930.0, 1970.0]
    assert sup.tv_sl == hard_before
    assert sup.current_sl == radar_before
    assert sup._cancelled == 1
    assert sup._placed == 1
    assert any(a[1] == "UPDATE_TP" for a in sup.alerts)


def test_update_tp_ignores_flat():
    sup = _FakeSup()
    sup._pos = None
    out = sup._handle_update_tp(_payload())
    assert out["status"] == "skipped"
    assert out["reason"] == "no_position"
    assert sup.tv_tps == [1800.0, 1850.0, 1900.0]
    assert sup._cancelled == 0
    assert sup._placed == 0


def test_update_tp_rejects_long_tp1_below_mark():
    sup = _FakeSup()
    sup._mark = 2000.0
    out = sup._handle_update_tp(_payload(tv_tp1=1900.5))
    assert out["status"] == "skipped"
    assert out["reason"] == "tp1_not_above_mark"
    assert sup.tv_tps == [1800.0, 1850.0, 1900.0]
    assert sup._cancelled == 0


def test_update_tp_rejects_short_tp1_above_mark():
    sup = _FakeSup()
    sup.current_side = "SHORT"
    sup._pos = {"size": 1.0, "entry_price": 2000.0, "side": "SHORT"}
    sup._mark = 1900.0
    out = sup._handle_update_tp(_payload(side="SHORT", tv_tp1=1950.0, tv_tp2=1900.0, tv_tp3=1850.0))
    assert out["status"] == "skipped"
    assert out["reason"] == "tp1_not_below_mark"
    assert sup._cancelled == 0


def test_update_tp_idempotent_same_prices():
    sup = _FakeSup()
    sup.tv_tps = [1900.5, 1930.0, 1970.0]
    out = sup._handle_update_tp(_payload())
    assert out["status"] == "ok"
    assert out["reason"] == "idempotent"
    assert sup._cancelled == 0
    assert sup._placed == 0


def test_update_tp_deepcoin_path():
    sup = _FakeSup(exchange_id="deepcoin")
    sup._pos = {"size": 10, "entry_price": 1750.0, "posSide": "long"}
    out = sup._handle_update_tp(_payload())
    assert out["status"] == "ok"
    assert sup.tv_tps == [1900.5, 1930.0, 1970.0]
    assert sup._placed == 1
