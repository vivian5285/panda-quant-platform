"""Tests for trading DingTalk filter, trade log enrichment, and execution display status."""
from app.services.trade_logger import TradeLogger
from app.services.trading_alerts import should_push_trading_dingtalk
from app.services.trade_display_status import resolve_trade_display_status


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


def test_open_trade_stays_open_despite_cap_guard_error_log():
    """Regression: open book + cap-align ERROR log must not show as failed."""
    logs = [
        {"event_type": "OPEN", "message": "战神出击 SHORT"},
        {"event_type": "ERROR", "message": "档位纠偏中止(安全校验): unsafe_retain_ratio"},
    ]
    assert resolve_trade_display_status("open", logs) == "open"


def test_fatal_error_without_open_is_failed():
    logs = [{"event_type": "ERROR", "message": "余额不足，无法开仓"}]
    assert resolve_trade_display_status("", logs) == "error"


def test_closed_trade_shows_closed():
    logs = [
        {"event_type": "OPEN", "message": "open"},
        {"event_type": "CLOSE", "message": "close"},
    ]
    assert resolve_trade_display_status("closed", logs) == "closed"
