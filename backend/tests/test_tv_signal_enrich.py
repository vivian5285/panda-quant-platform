"""v6.9.75 minimal webhook enrichment."""

from app.services.tv_signal_enrich import (
    compute_tv_tps_from_regime,
    enrich_tv_signal,
)
from app.services.webhook_guard import validate_signal_payload
from app.services.webhook_payload import parse_webhook_payload


def test_v6975_minimal_long_entry_enriched():
    raw = '{"action":"LONG","secret":"528586","price":3500.0}'
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "LONG"
    assert data["regime"] in (1, 2, 3, 4)
    assert float(data["atr"]) > 0
    assert float(data["tv_tp1"]) > 3500
    assert "tv_tps" in (data.get("_enriched_fields") or [])
    ok, msg = validate_signal_payload(data)
    assert ok, msg


def test_compute_tv_tps_long_regime3():
    tps = compute_tv_tps_from_regime(3500.0, 25.0, 3, "LONG")
    assert tps[0] == 3532.5
    assert tps[1] == 3565.0
    assert tps[2] == 3595.0


def test_close_stoploss_parsed():
    raw = (
        '{"action":"CLOSE_STOPLOSS","secret":"528586","side":"LONG",'
        '"reason":"触碰硬止损","price":1779.33,"pnl_pct":-0.38}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "CLOSE_STOPLOSS"
    ok, _ = validate_signal_payload(data)
    assert ok


def test_v6975_full_entry_pine_webhook_preserved():
    """Pine buildEntryWebhook — regime/atr/tv_tp* must not be overwritten by enrich."""
    raw = (
        '{"action":"LONG","secret":"528586","price":3500.0,"regime":3,'
        '"atr":25.5,"tv_tp1":3533.15,"tv_tp2":3566.3,"tv_tp3":3596.9}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["regime"] == 3
    assert data["atr"] == 25.5
    assert data["tv_tp1"] == 3533.15
    assert data["tv_tp2"] == 3566.3
    assert data["tv_tp3"] == 3596.9
    assert not (data.get("_enriched_fields") or [])
    ok, msg = validate_signal_payload(data)
    assert ok, msg


def test_v6975_full_close_protect_parsed():
    raw = (
        '{"action":"CLOSE_PROTECT","secret":"528586","regime":2,"price":1779.5,'
        '"atr":18.2,"side":"LONG","reason":"动能衰竭","pnl_pct":-1.23}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["regime"] == 2
    assert data["atr"] == 18.2
    assert data["side"] == "LONG"
    ok, _ = validate_signal_payload(data)
    assert ok


def test_format_enrich_note_empty_when_pine_sent_full():
    from app.services.tv_signal_enrich import format_enrich_note

    payload = enrich_tv_signal(
        {
            "action": "LONG",
            "price": 3500.0,
            "regime": 3,
            "atr": 25.5,
            "tv_tp1": 3533.15,
            "tv_tp2": 3566.3,
            "tv_tp3": 3596.9,
        }
    )
    assert format_enrich_note(payload) == ""
