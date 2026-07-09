"""TV tv_sl hard stop sync — replaces fixed 10% when strategy sends activeStop."""

import pytest

from app.core.adverse_radar_guard import (
    TV_SL_TIER_MARKER,
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
