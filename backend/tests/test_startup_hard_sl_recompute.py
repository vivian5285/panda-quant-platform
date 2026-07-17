"""Startup VPS hard SL recompute — must replace stale TV/persisted stops."""

import pytest
from unittest.mock import MagicMock

from app.core.adverse_radar_guard import AdverseRadarMixin, ADVERSE_STOP_TOLERANCE
from app.core.startup_reconcile import (
    extract_tv_sl_reference,
    finalize_recovery_tv_params,
    recompute_vps_hard_sl_on_recovery,
)


def test_extract_tv_sl_reference():
    assert extract_tv_sl_reference({"tv_sl": 1800.0}, None) == 1800.0
    assert extract_tv_sl_reference(None, {"tv_sl": 0}) == 0.0


def test_recompute_overwrites_tight_tv_sl():
    class Host(AdverseRadarMixin):
        user_id = 1
        watched_entry = 1819.0
        current_side = "LONG"
        regime = 2
        current_atr = 16.65
        tv_sl = 1805.0  # old tight TV stop (must be replaced)

    host = Host()
    host._init_adverse_radar_fields()
    meta = recompute_vps_hard_sl_on_recovery(host, entry_px=1819.0, side="LONG", tv_sl_reference=1805.0)
    assert meta.get("sl_changed") is True
    assert host.tv_sl == pytest.approx(1819.0 - 16.65 * 1.89, rel=0.01)
    assert meta["prev_sl"] == pytest.approx(1805.0)


def test_finalize_recovery_recomputes_not_tv_sl():
    class Sup:
        tv_tps = [0.0, 0.0, 0.0]
        watched_entry = 1819.0
        current_side = "LONG"
        last_tv_side = "LONG"
        regime = 2
        current_atr = 16.65
        tv_sl = 1805.0

        def _recompute_vps_hard_sl(self, entry_px=None, *, payload=None, side=None):
            from app.core.vps_hard_sl import compute_vps_hard_sl
            meta = compute_vps_hard_sl(
                float(entry_px or self.watched_entry), side or self.current_side,
                self.current_atr, self.regime,
                tv_sl_reference=float((payload or {}).get("tv_sl") or 0) or None,
            )
            self.tv_sl = float(meta.get("stop_price") or 0)
            return meta

    sup = Sup()
    report = {"open_log_entry": 1819.0, "open_log_side": "LONG"}
    recovery = {
        "latest_tv": {"tv_sl": 1805.0, "regime": 2, "atr": 16.65},
        "open_log": {"entry": 1819.0, "side": "LONG"},
    }
    finalize_recovery_tv_params(sup, report, recovery)
    assert sup.tv_sl == pytest.approx(1819.0 - 16.65 * 1.89, rel=0.01)
    assert report.get("tv_sl_reference") == pytest.approx(1805.0)
    assert report["vps_hard_sl_meta"]["sl_changed"] is True


class _StartupProbe(AdverseRadarMixin):
    exchange_id = "binance"
    user_id = 1
    symbol = "ETHUSDT"
    current_side = "LONG"
    watched_entry = 1819.0
    tv_sl = 1766.55
    regime = 2
    current_atr = 16.65
    adverse_sl_armed = False
    adverse_sl_prices = []
    adverse_consumed_tiers = []
    client = MagicMock()

    def _recompute_vps_hard_sl(self, entry_px=None, *, payload=None, side=None):
        from app.core.vps_hard_sl import compute_vps_hard_sl
        meta = compute_vps_hard_sl(
            float(entry_px or self.watched_entry),
            side or self.current_side,
            self.current_atr,
            self.regime,
            tv_sl_reference=float((payload or {}).get("tv_sl") or 0) or None,
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
    # Old wrong entry-% stop (~1748); ATR×1.89 target ≈1787.53
    stale_px = 1748.06
    expected_px = 1819.0 - 16.65 * 1.89
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
        "stopPrice": f"{expected_px:.2f}",
        "price": f"{expected_px * (1 - 0.0015):.2f}",
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
