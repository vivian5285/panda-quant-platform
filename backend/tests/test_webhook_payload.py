"""Tests for TradingView webhook JSON parsing."""

from app.services.webhook_payload import parse_webhook_payload, repair_pine_close_protect_json
from app.services.webhook_guard import validate_signal_payload


def test_valid_close_protect():
    raw = (
        '{"action":"CLOSE_PROTECT","secret":"528586","regime":2,'
        '"side":"LONG","reason":"动能衰竭","pnl_pct":-1.23}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "CLOSE_PROTECT"
    assert data["side"] == "LONG"
    assert data["reason"] == "动能衰竭"


def test_repair_pine_v6930_malformed_close_protect():
    # Exact bug from 万亿战神 v6.9.30: missing closing quotes on side/reason
    raw = (
        '{"action":"CLOSE_PROTECT","secret":"528586","regime":2,'
        '"side":"LONG,"reason":"高优拦截：致命组合裸K看跌,"pnl_pct":-1.50}'
    )
    repaired = repair_pine_close_protect_json(raw)
    assert repaired is not None
    assert '"side":"LONG","reason":"高优拦截：致命组合裸K看跌","pnl_pct":' in repaired

    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "CLOSE_PROTECT"
    assert data["side"] == "LONG"
    assert "裸K" in data["reason"]


def test_tv_screenshot_close_protect_payload():
    """Exact payload shape from TradingView alert log (pnl_pct as string)."""
    raw = (
        '{"action":"CLOSE_PROTECT","secret":"528586","regime":2,'
        '"side":"SHORT","reason":"高优拦截：致命组合裸K看涨","pnl_pct":"-1.08"}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "CLOSE_PROTECT"
    assert data["side"] == "SHORT"
    assert data["pnl_pct"] == -1.08
    assert "裸K" in data["reason"]


def test_v6975_minimal_entry_after_enrich_validates():
    raw = '{"action":"LONG","secret":"528586","symbol":"ETHUSDT.P","price":3500}'
    data, err = parse_webhook_payload(raw)
    assert err is None
    ok, msg = validate_signal_payload(data)
    assert ok, msg


def test_invalid_json_still_rejected():
    data, err = parse_webhook_payload('{"action":')
    assert data is None
    assert err and "Invalid JSON" in err


def test_empty_payload():
    data, err = parse_webhook_payload("")
    assert data is None
    assert err == "Empty payload"


def test_v6975_close_stoploss_breakeven():
    raw = (
        '{"action":"CLOSE_STOPLOSS","secret":"528586","regime":2,'
        '"price":3456.78,"atr":42.5,"side":"LONG",'
        '"reason":"防回吐保本平仓","pnl_pct":0.05}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "CLOSE_STOPLOSS"
    assert data["reason"] == "防回吐保本平仓"
    assert data["pnl_pct"] == 0.05


def test_v6975_close_stoploss_hard():
    raw = (
        '{"action":"CLOSE_STOPLOSS","secret":"528586","regime":2,'
        '"price":3200.0,"atr":40.0,"side":"SHORT",'
        '"reason":"触碰硬止损平仓","pnl_pct":-10.02}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "CLOSE_STOPLOSS"
    assert "硬止损" in data["reason"]


def test_v6975_close_tp3():
    raw = (
        '{"action":"CLOSE_TP3","secret":"528586","regime":3,'
        '"price":3600.0,"atr":30.0,"side":"SHORT",'
        '"reason":"TP3完美收网","pnl_pct":2.5}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "CLOSE_TP3"
    assert data["reason"] == "TP3完美收网"


def test_v6975_entry_with_tv_sl():
    raw = (
        '{"action":"LONG","secret":"528586","price":70000,"regime":3,'
        '"atr":42.5,"tv_tp1":70500,"tv_tp2":71000,"tv_tp3":72000,'
        '"tv_sl":64428}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "LONG"
    assert data["tv_sl"] == 64428


def test_v6975_update_sl():
    raw = '{"action":"UPDATE_SL","secret":"528586","side":"LONG","tv_sl":64500}'
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "UPDATE_SL"
    assert data["tv_sl"] == 64500


def test_v69108_update_tp_validates():
    raw = (
        '{"action":"UPDATE_TP","secret":"528586","symbol":"ETHUSDT.P","side":"LONG",'
        '"tv_tp1":1900.50,"tv_tp2":1930.00,"tv_tp3":1970.00}'
    )
    data, err = parse_webhook_payload(raw)
    assert err is None
    assert data["action"] == "UPDATE_TP"
    ok, msg = validate_signal_payload(data)
    assert ok, msg
    assert data["tv_tp1"] == 1900.50


def test_v69108_update_tp_requires_tps():
    ok, msg = validate_signal_payload({
        "action": "UPDATE_TP",
        "symbol": "ETHUSDT",
        "side": "LONG",
        "tv_tp1": 1900,
        "tv_tp2": 0,
        "tv_tp3": 1970,
    })
    assert not ok
    assert "tv_tp2" in msg
