"""Tests for TradingView webhook JSON parsing."""

from app.services.webhook_payload import parse_webhook_payload, repair_pine_close_protect_json


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


def test_invalid_json_still_rejected():
    data, err = parse_webhook_payload('{"action":')
    assert data is None
    assert err and "Invalid JSON" in err


def test_empty_payload():
    data, err = parse_webhook_payload("")
    assert data is None
    assert err == "Empty payload"
