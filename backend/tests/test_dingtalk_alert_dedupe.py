"""DingTalk once-per-event / cooldown — no monitor-loop spam."""

from __future__ import annotations

from app.services.dingtalk_alert_dedupe import (
    allow_trading_dingtalk,
    reset_dingtalk_dedupe_for_tests,
)


def test_tp_filled_once_same_fingerprint():
    reset_dingtalk_dedupe_for_tests()
    detail = {
        "exchange": "binance",
        "symbol": "ETHUSDT",
        "level": 1,
        "old_qty": 0.244,
        "new_qty": 0.231,
        "side": "LONG",
    }
    assert allow_trading_dingtalk(
        1, "TP_FILLED", "止盈TP1成交·不再补挂", "LONG 0.244→0.231", detail,
    )
    assert not allow_trading_dingtalk(
        1, "TP_FILLED", "止盈TP1成交·不再补挂", "LONG 0.244→0.231", detail,
    )


def test_tp2_different_level_allowed():
    reset_dingtalk_dedupe_for_tests()
    d1 = {"exchange": "binance", "symbol": "ETHUSDT", "level": 1, "old_qty": 0.2, "new_qty": 0.15}
    d2 = {"exchange": "binance", "symbol": "ETHUSDT", "level": 2, "old_qty": 0.15, "new_qty": 0.1}
    assert allow_trading_dingtalk(1, "TP_FILLED", "止盈TP1成交·不再补挂", "a", d1)
    assert allow_trading_dingtalk(1, "TP_FILLED", "止盈TP2成交·不再补挂", "b", d2)


def test_reconcile_cooldown():
    reset_dingtalk_dedupe_for_tests()
    detail = {"exchange": "okx", "symbol": "ETHUSDT"}
    assert allow_trading_dingtalk(2, "POSITION_RECONCILE", "对账", "ok", detail)
    assert not allow_trading_dingtalk(2, "POSITION_RECONCILE", "对账", "ok", detail)


def test_different_exchange_not_blocked():
    reset_dingtalk_dedupe_for_tests()
    d_bn = {"exchange": "binance", "symbol": "ETHUSDT", "level": 1, "old_qty": 1, "new_qty": 0.5}
    d_ok = {"exchange": "okx", "symbol": "ETHUSDT", "level": 1, "old_qty": 1, "new_qty": 0.5}
    assert allow_trading_dingtalk(1, "TP_FILLED", "止盈TP1成交·不再补挂", "m", d_bn)
    assert allow_trading_dingtalk(1, "TP_FILLED", "止盈TP1成交·不再补挂", "m", d_ok)
