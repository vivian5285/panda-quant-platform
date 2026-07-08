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


def test_supervisor_fallback_regime_atr():
    payload = enrich_tv_signal(
        {"action": "SHORT", "price": 3600.0},
        fallback_regime=2,
        fallback_atr=18.5,
    )
    assert payload["regime"] == 2
    assert payload["atr"] == 18.5
    assert payload["tv_tp3"] < 3600
