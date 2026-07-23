"""Market engine wiring — VPS ATR/ADX only; ATR mismatch is alert-only."""

from unittest.mock import MagicMock, patch

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.breathing_stop import INITIAL_SL_ATR
from app.core.market_engine import (
    atr_mismatch_ratio,
    clear_cache,
    implied_atr_from_tv_stop,
)
from app.services.tv_signal_enrich import enrich_tv_signal


class _Stub(AdverseRadarMixin):
    def __init__(self):
        self.user_id = 1
        self.exchange_id = "binance"
        self.symbol = "ETHUSDT"
        self.canonical_symbol = "ETHUSDT"
        self.client = MagicMock()
        self.client.exchange_id = "binance"
        self.client.canonical_symbol = "ETHUSDT"
        self.client.trading_symbol = "ETHUSDT"
        self.alerts = []
        self.monitoring = False
        self.watched_qty = 0.0
        self.current_side = "LONG"
        self.watched_entry = 1800.0
        self.current_atr = 0.0
        self.current_adx = 25.0
        self.initial_atr = 0.0
        self.initial_stop = 0.0
        self.current_sl = 0.0
        self.tv_sl = 0.0

    def _alert(self, severity, atype, title, message, detail=None):
        self.alerts.append({
            "severity": severity,
            "type": atype,
            "title": title,
            "message": message,
            "detail": detail or {},
        })


def test_implied_atr_from_tv_stop():
    assert abs(implied_atr_from_tv_stop(1800, 1740, initial_sl_atr=1.5) - 40) < 1e-9
    assert abs(implied_atr_from_tv_stop(1800, 1760, initial_sl_atr=1.0) - 40) < 1e-9
    assert implied_atr_from_tv_stop(0, 1740) == 0


def test_atr_mismatch_ratio():
    assert atr_mismatch_ratio(40, 40) == 0
    assert abs(atr_mismatch_ratio(40, 48) - 0.2) < 1e-9


def test_enrich_does_not_invent_atr():
    out = enrich_tv_signal({
        "action": "LONG",
        "price": 1800,
        "stop_loss": 1740,
        "tp1": 1854,
        "tp2": 1900,
    })
    assert "atr" not in out or float(out.get("atr") or 0) == 0
    assert out["tv_sl"] == 1740


def test_recompute_prefers_vps_1h_not_payload_or_90m():
    clear_cache()
    stub = _Stub()
    with patch(
        "app.core.adverse_radar_guard.fetch_vps_1h_atr_fresh",
        return_value=(40.0, True),
    ):
        meta = stub._recompute_vps_hard_sl(
            payload={"action": "LONG", "price": 1800, "atr": 999, "adx": 5, "stop_loss": 1740},
            side="LONG",
        )
    assert abs(meta["atr"] - 40.0) < 1e-9
    assert meta["atr_source"] == "vps_1h"
    assert abs(stub.current_atr - 40.0) < 1e-9
    assert abs(meta["stop_price"] - (1800 - INITIAL_SL_ATR * 40)) < 1e-6
    # TV atr stored as ref only
    assert abs(float(stub._tv_atr_ref) - 999) < 1e-9


def test_recompute_falls_back_to_tv_atr_when_1h_fails():
    clear_cache()
    stub = _Stub()
    with patch(
        "app.core.adverse_radar_guard.fetch_vps_1h_atr_fresh",
        return_value=(0.0, False),
    ):
        meta = stub._recompute_vps_hard_sl(
            payload={"action": "LONG", "price": 1800, "atr": 50, "stop_loss": 1740},
            side="LONG",
        )
    assert abs(meta["atr"] - 50.0) < 1e-9
    assert meta["atr_source"] == "tv_webhook"


def test_atr_mismatch_alerts_when_over_threshold():
    clear_cache()
    stub = _Stub()
    # TV_STOP_ATR_MULT=1.0: |1800-1700|/1.0=100 vs VPS=40 → 150% mismatch
    stub._maybe_alert_atr_mismatch(1800, 1700, 40)
    types = [a["type"] for a in stub.alerts]
    assert "ATR_MISMATCH" in types


def test_atr_mismatch_silent_when_tv_1x_matches_vps():
    """Regression: TV stop≈1.0×ATR must NOT false-alarm ~33% vs VPS ATR."""
    stub = _Stub()
    # |1930.49 - 1915.65| / 1.0 ≈ 14.84 ≈ VPS ATR
    stub._maybe_alert_atr_mismatch(1930.49, 1915.65, 14.8288)
    assert stub.alerts == []


def test_atr_mismatch_silent_when_close():
    stub = _Stub()
    # Exact match under TV_STOP_ATR_MULT=1.0
    stub._maybe_alert_atr_mismatch(1800, 1760, 40)
    assert stub.alerts == []


def test_live_incident_atr_was_false_positive_under_old_1p5():
    """2026-07-22 ding alerts Δ29%~33% = wrong divisor 1.5 on matched ATRs."""
    vps = 14.8288
    entry, stop = 1930.49, 1915.6471582505
    wrong = implied_atr_from_tv_stop(entry, stop, initial_sl_atr=1.5)
    right = implied_atr_from_tv_stop(entry, stop, initial_sl_atr=1.0)
    assert atr_mismatch_ratio(vps, wrong) > 0.25
    assert atr_mismatch_ratio(vps, right) < 0.05


def test_live_position_soft_refresh_does_not_reset_stop():
    clear_cache()
    stub = _Stub()
    stub.monitoring = True
    stub.watched_qty = 1.0
    stub.initial_atr = 40.0
    stub.initial_stop = 1740.0
    stub.current_sl = 1756.0
    stub.tv_sl = 1756.0
    with patch(
        "app.core.adverse_radar_guard.ensure_fresh",
        return_value={"atr": 99.0, "adx": 33.0, "source": "test"},
    ):
        px = stub._apply_tv_sl_from_payload({"atr": 1, "adx": 1, "stop_loss": 1000})
    assert px == 1756.0
    assert stub.initial_atr == 40.0
    assert stub.current_adx == 33.0
