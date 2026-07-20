"""TV tv_sl hard stop sync — replaces fixed 10% when strategy sends activeStop."""

import pytest

from app.core.adverse_radar_guard import (
    TV_SL_TIER_MARKER,
    AdverseRadarMixin,
    compute_adverse_stop_plan,
    parse_tv_sl,
)
from app.services.webhook_guard import validate_signal_payload


def test_parse_tv_sl():
    assert parse_tv_sl(64428.0) == 64428.0
    assert parse_tv_sl("64500.5") == 64500.5
    assert parse_tv_sl(None) is None
    assert parse_tv_sl(0) is None


def test_compute_adverse_stop_plan_uses_tv_sl():
    plan = compute_adverse_stop_plan(
        70000.0,
        "LONG",
        0.5,
        round_qty_fn=lambda q: round(q, 3),
        tv_sl_price=64428.0,
    )
    assert len(plan) == 1
    assert plan[0]["stop_price"] == 64428.0
    assert plan[0]["tier_pct"] == TV_SL_TIER_MARKER
    assert plan[0]["source"] == "tv_hard_sl"


def test_compute_adverse_stop_plan_empty_without_tv_sl():
    plan = compute_adverse_stop_plan(
        2000.0,
        "LONG",
        0.6,
        round_qty_fn=lambda q: q,
    )
    assert plan == []


def test_validate_update_sl_payload():
    ok, msg = validate_signal_payload({
        "action": "UPDATE_SL",
        "secret": "528586",
        "symbol": "ETHUSDT",
        "side": "LONG",
        "tv_sl": 64500,
    })
    assert ok, msg


def test_validate_update_sl_rejects_missing_side():
    ok, msg = validate_signal_payload({
        "action": "UPDATE_SL",
        "secret": "528586",
        "symbol": "ETHUSDT",
        "tv_sl": 64500,
    })
    assert not ok
    assert "side" in msg


def test_merged_stop_price_long():
    class Probe(AdverseRadarMixin):
        current_side = "LONG"
        tv_sl = 1800.0
        current_sl = 2050.0
        watched_entry = 2000.0
        radar_latched = True

    probe = Probe()
    assert probe._merged_stop_price() == 2050.0


def test_update_sl_applies_tv_hard_sl():
    class Probe(AdverseRadarMixin):
        exchange_id = "binance"
        symbol = "ETHUSDT"
        user_id = 1
        current_side = "LONG"
        tv_sl = 1766.0
        regime = 2
        current_atr = 16.65
        watched_qty = 0.5
        logs = []
        sync_calls = []

        def _log(self, *a, **k):
            self.logs.append(a)

        def _alert(self, *a, **k):
            pass

        def _get_active_position(self):
            return {"size": 0.5, "side": "LONG", "entry_price": 1819.0}

        def _sync_tv_hard_stop(self, live_qty, force_replace=False, **kwargs):
            self.sync_calls.append((live_qty, force_replace))
            return {"armed": True, "stop_price": self.tv_sl}

    probe = Probe()
    probe._init_adverse_radar_fields()
    result = probe._handle_update_sl({
        "side": "LONG", "regime": 2, "atr": 16.65, "tv_sl": 1800.0,
    })
    assert result["status"] == "ok"
    assert result["detail"]["ignored"] is False
    assert probe.tv_sl == pytest.approx(1800.0)
    assert probe._tv_hard_sl_price == pytest.approx(1800.0)
    assert probe.sync_calls and probe.sync_calls[0][1] is True


def test_update_sl_missing_tv_sl_skipped():
    class Probe(AdverseRadarMixin):
        exchange_id = "binance"
        user_id = 1
        tv_sl = 1766.0
        regime = 2
        current_atr = 16.65

        def _log(self, *a, **k):
            pass

        def _get_active_position(self):
            return None

    probe = Probe()
    probe._init_adverse_radar_fields()
    result = probe._handle_update_sl({"side": "LONG", "tv_sl": 0})
    assert result["status"] == "skipped"
    assert result["reason"] == "missing_tv_sl"


def test_entry_payload_accepts_tv_sl():
    ok, msg = validate_signal_payload({
        "action": "LONG",
        "secret": "528586",
        "symbol": "ETHUSDT",
        "price": 70000,
        "regime": 3,
        "atr": 30,
        "tv_sl": 64428,
        "risk_pct": 2.03,
        "leverage": 25,
        "qty_ratio": 1.0,
    })
    assert ok, msg
