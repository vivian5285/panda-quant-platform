"""Webhook enrichment — ATR/ADX not invented; TP1/TP2 required from TV."""

import pytest

from app.services.tv_signal_enrich import (
    compute_tv_tps_from_regime,
    enrich_tv_signal,
    format_enrich_note,
)
from app.services.webhook_guard import validate_signal_payload
from app.services.webhook_payload import parse_webhook_payload


def test_entry_without_tps_fails_validation():
    """VPS does not invent TP from regime — TV must send tp1/tp2."""
    raw = (
        '{"action":"LONG","secret":"528586","symbol":"ETHUSDT","price":3500.0,'
        '"risk_pct":2.03,"leverage":25,"tv_sl":3450.0,"qty_ratio":1.0}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "LONG"
    # ATR no longer invented for decision path
    assert float(data.get("atr") or 0) == 0
    ok, msg = validate_signal_payload(data)
    assert not ok


def test_compute_tv_tps_from_regime_market_ladder():
    """Recovery/manual adopt may derive TP ladder from ATR (webhook still requires TV tp)."""
    tps = compute_tv_tps_from_regime(3500.0, 25.0, 3, "LONG")
    assert tps[0] == pytest.approx(3500.0 + 1.35 * 25.0)
    assert tps[1] == pytest.approx(3500.0 + 2.5 * 25.0)
    assert tps[2] == pytest.approx(3500.0 + 4.0 * 25.0)


def test_legacy_close_stoploss_rejected():
    raw = (
        '{"action":"CLOSE_STOPLOSS","secret":"528586","symbol":"ETHUSDT","side":"LONG",'
        '"reason":"触碰硬止损","price":1779.33,"pnl_pct":-0.38}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "CLOSE_STOPLOSS"
    ok, msg = validate_signal_payload(data)
    assert not ok
    assert "Unsupported" in msg or "CLOSE" in msg


def test_full_entry_pine_webhook_preserved():
    """Pine atr kept on payload for debug only; TPs preserved."""
    raw = (
        '{"action":"LONG","secret":"528586","symbol":"ETHUSDT","price":3500.0,"regime":3,'
        '"atr":25.5,"tv_tp1":3533.15,"tv_tp2":3566.3,"tv_tp3":3596.9,'
        '"tv_sl":3400,"risk_pct":2.03,"leverage":25,"qty_ratio":1.0}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["regime"] == 3
    assert data["atr"] == 25.5
    assert data["tv_tp1"] == 3533.15
    assert data["tv_tp2"] == 3566.3
    assert data["tv_tp3"] == 3596.9
    ok, msg = validate_signal_payload(data)
    assert ok, msg


def test_legacy_close_protect_rejected():
    raw = (
        '{"action":"CLOSE_PROTECT","secret":"528586","symbol":"ETHUSDT","regime":2,"price":1779.5,'
        '"atr":18.2,"side":"LONG","reason":"动能衰竭","pnl_pct":-1.23}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "CLOSE_PROTECT"
    ok, msg = validate_signal_payload(data)
    assert not ok


def test_format_enrich_note_empty_when_pine_sent_full():
    payload = enrich_tv_signal(
        {
            "action": "LONG",
            "price": 3500.0,
            "regime": 3,
            "atr": 25.5,
            "tv_tp1": 3533.15,
            "tv_tp2": 3566.3,
            "tv_tp3": 3596.9,
            "stop_loss": 3400,
        }
    )
    assert format_enrich_note(payload) == ""
