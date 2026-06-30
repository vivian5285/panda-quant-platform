"""Tests for trading DingTalk filter and trade log enrichment."""
from app.services.trade_logger import TradeLogger
from app.services.trading_alerts import should_push_trading_dingtalk


def test_dingtalk_only_key_actions():
    assert should_push_trading_dingtalk("OPEN", "info") is True
    assert should_push_trading_dingtalk("CLOSE", "info") is True
    assert should_push_trading_dingtalk("DEFENSE_HEAL_FAIL", "critical") is True
    assert should_push_trading_dingtalk("TRAIL", "info") is False
    assert should_push_trading_dingtalk("DEFENSE_HEAL", "warning") is False
    assert should_push_trading_dingtalk("DEFENSE_HEAL_OK", "info") is False
    assert should_push_trading_dingtalk("DEFENSE_AUDIT", "info") is False
    assert should_push_trading_dingtalk("UNKNOWN", "critical") is True


def test_trade_log_enrich_detail():
    d = TradeLogger.enrich_detail({"side": "LONG", "qty": 1.0}, "OPEN")
    assert d["live_verified"] is True
    assert d["source"] == "platform_supervisor"
    assert "verified_at" in d

    fill = TradeLogger.enrich_detail({"price": 3000}, "BINANCE_FILL")
    assert fill.get("live_verified") is None
    assert fill["source"] == "binance_exchange_sync"
