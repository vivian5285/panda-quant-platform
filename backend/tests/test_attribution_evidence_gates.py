"""Attribution must not assert without evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.core.close_attribution import diagnose_flat_close
from app.services.trading_alerts import format_close_detail_cn


def test_format_close_detail_does_not_call_any_reason_reverse_protect():
    body = format_close_detail_cn(
        {
            "reason": "仓位归零 (止盈吃单 / 人工全平 / TV 强制平仓)",
            "exit_price": 1910.0,
            "close_action": "",
        }
    )
    assert "反转保护" not in body
    assert "全平完成" in body or "证据不足" in body or "说明" in body


def test_maker_fills_without_tp_price_match_are_insufficient():
    attr = diagnose_flat_close(
        client=MagicMock(get_account_trades=MagicMock(return_value=[
            {
                "side": "SELL",
                "price": "1933.00",  # not near TP1 1925.97 / TP2 / stop
                "qty": "0.033",
                "maker": True,
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
                "realizedPnl": "1.0",
            },
        ])),
        symbol="ETHUSDT",
        side="LONG",
        qty=0.033,
        entry=1918.0,
        trade_opened_at=datetime.now(timezone.utc).timestamp() - 3600,
        consumed_tp_levels=[],
        tv_tps=[1925.97, 1940.78, 1955.58],
        trigger="sentinel_zero",
        had_position_before_close=False,
        radar_active=False,
        current_sl=1890.0,
    )
    assert attr["close_origin"] != "exchange_limit_tp"
    assert attr["confidence"] == "insufficient"
    assert "待核实" in attr["human_reason"]


def test_peak_tp3_without_exit_evidence_not_asserted():
    attr = diagnose_flat_close(
        client=MagicMock(get_account_trades=MagicMock(return_value=[
            {
                "side": "SELL",
                "price": "1930.00",  # between TPs, far from stop & TP3
                "qty": "0.033",
                "maker": False,
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
                "realizedPnl": "0.5",
            },
        ])),
        symbol="ETHUSDT",
        side="LONG",
        qty=0.033,
        entry=1910.0,
        trade_opened_at=datetime.now(timezone.utc).timestamp() - 3600,
        consumed_tp_levels=[],
        tv_tps=[1925.0, 1940.0, 1955.0],
        trigger="sentinel_zero",
        had_position_before_close=False,
        radar_active=True,
        current_sl=1880.0,  # exit not near stop
        peak_price=1956.0,  # peak past TP3
        exit_price=1930.0,
    )
    assert attr["close_origin"] != "radar_tp3_trail"
    assert attr["confidence"] == "insufficient"
    assert "证据不足" in attr["human_reason"]


def test_had_position_without_platform_market_not_forced_platform():
    attr = diagnose_flat_close(
        client=MagicMock(get_account_trades=MagicMock(return_value=[])),
        symbol="ETHUSDT",
        side="LONG",
        qty=0.033,
        entry=1918.0,
        trade_opened_at=None,
        consumed_tp_levels=[],
        tv_tps=[1925.0, 1940.0, 1955.0],
        trigger="code_close_all",
        had_position_before_close=True,
        platform_initiated_market=False,
        radar_active=False,
    )
    assert attr["close_origin"] != "platform_market"
    assert attr["confidence"] == "insufficient"
