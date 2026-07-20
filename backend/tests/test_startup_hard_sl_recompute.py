"""Startup hard SL — must use TV tv_sl, never VPS entry×regime overwrite."""

import pytest
from unittest.mock import MagicMock

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.startup_reconcile import (
    extract_tv_sl_reference,
    finalize_recovery_tv_params,
    recompute_vps_hard_sl_on_recovery,
)


def test_extract_tv_sl_reference():
    assert extract_tv_sl_reference({"tv_sl": 1800.0}, None) == 1800.0
    assert extract_tv_sl_reference(None, {"tv_sl": 0}) == 0.0


def test_recompute_uses_tv_sl_not_regime_pct():
    class Host(AdverseRadarMixin):
        user_id = 1
        watched_entry = 1819.0
        current_side = "LONG"
        regime = 2
        current_atr = 16.65
        tv_sl = 0.0

    host = Host()
    host._init_adverse_radar_fields()
    meta = recompute_vps_hard_sl_on_recovery(
        host, entry_px=1819.0, side="LONG", tv_sl_reference=1787.0,
    )
    assert host.tv_sl == pytest.approx(1787.0)
    assert meta.get("source") == "tv_sl"
    # Must NOT become entry × (1 - 3.89%)
    assert host.tv_sl != pytest.approx(1819.0 * (1 - 0.0389), rel=0.01)


def test_finalize_recovery_uses_tv_sl():
    class Sup:
        tv_tps = [0.0, 0.0, 0.0]
        watched_entry = 1819.0
        current_side = "LONG"
        last_tv_side = "LONG"
        regime = 2
        current_atr = 16.65
        tv_sl = 0.0
        _tv_hard_sl_price = 0.0

        def _recompute_vps_hard_sl(self, entry_px=None, *, payload=None, side=None):
            from app.core.vps_hard_sl import compute_vps_hard_sl
            ref = float((payload or {}).get("tv_sl") or 0) or None
            meta = compute_vps_hard_sl(
                float(entry_px or self.watched_entry), side or self.current_side,
                self.current_atr, self.regime,
                tv_sl_reference=ref,
            )
            self.tv_sl = float(meta.get("stop_price") or 0)
            if ref:
                self._tv_hard_sl_price = float(ref)
            return meta

    sup = Sup()
    report = {"open_log_entry": 1819.0, "open_log_side": "LONG"}
    recovery = {
        "latest_tv": {"tv_sl": 1787.0, "regime": 2, "atr": 16.65},
        "open_log": {"entry": 1819.0, "side": "LONG"},
    }
    finalize_recovery_tv_params(sup, report, recovery)
    assert sup.tv_sl == pytest.approx(1787.0)
    assert report.get("tv_sl_reference") == pytest.approx(1787.0)


class _StartupProbe(AdverseRadarMixin):
    exchange_id = "binance"
    user_id = 1
    symbol = "ETHUSDT"
    current_side = "LONG"
    watched_entry = 1819.0
    tv_sl = 1787.0
    _tv_hard_sl_price = 1787.0
    regime = 2
    current_atr = 16.65
    adverse_sl_armed = False
    adverse_sl_prices = []
    adverse_consumed_tiers = []
    client = MagicMock()

    def _recompute_vps_hard_sl(self, entry_px=None, *, payload=None, side=None):
        from app.core.vps_hard_sl import compute_vps_hard_sl
        ref = float((payload or {}).get("tv_sl") or getattr(self, "_tv_hard_sl_price", 0) or 0) or None
        meta = compute_vps_hard_sl(
            float(entry_px or self.watched_entry),
            side or self.current_side,
            self.current_atr,
            self.regime,
            tv_sl_reference=ref,
        )
        self.tv_sl = float(meta.get("stop_price") or 0)
        return meta

    def _adverse_round_qty(self, qty):
        return round(qty, 3)

    def _get_active_position(self):
        return {"size": 0.6, "side": "LONG", "entry_price": 1819.0}

    def _close_order_side(self):
        return "SELL"

    def _log(self, *a, **k):
        pass

    def _alert(self, *a, **k):
        pass

    def _save_state(self):
        pass


def test_startup_reconcile_upgrades_stale_stop_on_book():
    probe = _StartupProbe()
    probe._init_adverse_radar_fields()
    probe._tv_hard_sl_price = 1748.06
    probe.tv_sl = 1748.06
    stale_px = 1787.0
    stop_order = {
        "type": "STOP",
        "orderId": 1,
        "stopPrice": str(stale_px),
        "price": str(stale_px - 0.5),
        "origQty": "0.6",
        "side": "SELL",
    }
    new_stop = {
        "type": "STOP",
        "orderId": 2,
        "stopPrice": "1748.06",
        "price": "1745.44",
        "origQty": "0.6",
        "side": "SELL",
    }
    cancelled_flag = {"done": False}

    def _open_orders(_symbol):
        if not cancelled_flag["done"]:
            return [stop_order]
        return [new_stop]

    def _cancel(*_a, **_k):
        cancelled_flag["done"] = True
        return True

    probe.client.get_open_orders.side_effect = _open_orders
    probe.client.cancel_order.side_effect = _cancel
    probe.client.place_stop_limit_order.return_value = {"orderId": 2}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.core.adverse_radar_guard.time.sleep", lambda *_: None)
        audit = probe._on_adverse_startup_reconcile(0.6, 1820.0)

    assert audit.get("startup_stale_stop") is True
    assert audit.get("stale_stop_px") == pytest.approx(stale_px)
    probe.client.cancel_order.assert_called()
