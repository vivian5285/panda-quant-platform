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
    assert plan[0]["source"] == "tv_sl"


def test_compute_adverse_stop_plan_fallback_10pct():
    plan = compute_adverse_stop_plan(
        2000.0,
        "LONG",
        0.6,
        round_qty_fn=lambda q: q,
    )
    assert len(plan) == 1
    assert plan[0]["stop_price"] == pytest.approx(1800.0, rel=0.001)
    assert plan[0]["source"] == "pct10"


def test_validate_update_sl_payload():
    ok, msg = validate_signal_payload({
        "action": "UPDATE_SL",
        "secret": "528586",
        "side": "LONG",
        "tv_sl": 64500,
    })
    assert ok, msg


def test_validate_update_sl_rejects_missing_side():
    ok, msg = validate_signal_payload({
        "action": "UPDATE_SL",
        "secret": "528586",
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

        def _is_radar_active(self):
            return True

    probe = Probe()
    assert probe._merged_stop_price() == 2050.0


def test_update_sl_still_applies_when_radar_active():
    class Probe(AdverseRadarMixin):
        exchange_id = "binance"
        symbol = "ETHUSDT"
        user_id = 1
        current_side = "LONG"
        watched_entry = 2000.0
        current_sl = 2050.0
        tv_sl = 1800.0
        client = type("C", (), {"get_current_price": lambda _s, _sym: 2050.0})()

        def _get_active_position(self):
            return {"size": 0.5, "side": "LONG"}

        def _is_radar_active(self):
            return True

        def _uses_dual_stop_track(self):
            return False

        def _sync_binance_merged_stop(self, live_qty, **kwargs):
            return {"aligned": True, "stop_price": 2050.0, "merged": True, "placed": 0}

        def _sync_adverse_shield_from_exchange(self, live_qty):
            return {"aligned": False}

        def _log(self, *a, **k):
            pass

        def _alert(self, *a, **k):
            pass

        def _save_state(self):
            pass

        def _hard_stop_label(self):
            return "TV硬止损"

    probe = Probe()
    probe._init_adverse_radar_fields()
    result = probe._handle_update_sl({"side": "LONG", "tv_sl": 1900.0})
    assert result["status"] == "ok"
    assert result["detail"].get("skipped") != "radar_takeover"
    assert probe.tv_sl == 1900.0


def test_update_sl_allowed_before_radar():
    class Probe(AdverseRadarMixin):
        exchange_id = "binance"
        symbol = "ETHUSDT"
        user_id = 1
        current_side = "LONG"
        watched_entry = 2000.0
        current_sl = 2000.0
        tv_sl = 1800.0
        adverse_sl_armed = True
        adverse_sl_prices = [1800.0]
        client = type("C", (), {"get_current_price": lambda _s, _sym: 2010.0})()

        def _get_active_position(self):
            return {"size": 0.5, "side": "LONG"}

        def _log(self, *a, **k):
            pass

        def _save_state(self):
            pass

        def _uses_dual_stop_track(self):
            return False

        def _sync_binance_merged_stop(self, live_qty, **kwargs):
            return {"armed": True, "placed": 1, "stop_price": 1900.0, "label": "TV硬止损", "aligned": True}

        def _sync_adverse_shield_from_exchange(self, live_qty):
            return {"aligned": False}

        def _alert(self, *a, **k):
            pass

        def _is_radar_active(self):
            return False

        def _hard_stop_label(self):
            return "TV硬止损"

    probe = Probe()
    probe._init_adverse_radar_fields()
    result = probe._handle_update_sl({"side": "LONG", "tv_sl": 1900.0})
    assert result["status"] == "ok"
    assert result["detail"].get("skipped") != "radar_takeover"


def test_entry_payload_accepts_tv_sl():
    ok, msg = validate_signal_payload({
        "action": "LONG",
        "secret": "528586",
        "price": 70000,
        "regime": 3,
        "atr": 30,
        "tv_sl": 64428,
    })
    assert ok, msg
