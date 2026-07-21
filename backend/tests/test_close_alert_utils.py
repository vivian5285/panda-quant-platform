"""Tests for TV close alert classification and detail fields (精准风控 v6.9.75)."""

from app.services.close_alert_utils import (
    build_close_detail,
    build_verify_note,
    classify_tv_close_subtype,
    extract_tv_close_fields,
    resolve_close_alert_title,
    resolve_close_alert_type,
)


def test_extract_tv_close_fields_v6975():
    payload = {
        "action": "CLOSE_STOPLOSS",
        "secret": "528586",
        "regime": 2,
        "price": 3456.78,
        "atr": 42.5,
        "side": "LONG",
        "reason": "防回吐保本平仓",
        "pnl_pct": 0.05,
    }
    fields = extract_tv_close_fields(payload)
    assert fields["close_action"] == "CLOSE_STOPLOSS"
    assert fields["tv_reason"] == "防回吐保本平仓"
    assert fields["tv_side"] == "LONG"
    assert fields["tv_pnl_pct"] == 0.05
    assert fields["tv_regime"] == 2
    assert fields["tv_atr"] == 42.5
    assert fields["tv_price"] == 3456.78


def test_classify_breakeven_vs_hard_stop():
    assert classify_tv_close_subtype("CLOSE_STOPLOSS", "防回吐保本平仓") == "breakeven"
    assert classify_tv_close_subtype("CLOSE_STOPLOSS", "触碰硬止损平仓") == "hard_stop"
    assert classify_tv_close_subtype("CLOSE_TP3", "TP3完美收网") == "tp3"
    assert classify_tv_close_subtype("CLOSE_PROTECT", "风控拦截：动能衰竭") == "risk_intercept"
    assert classify_tv_close_subtype("CLOSE_PROTECT", "高优拦截：裸K") == "risk_intercept"


def test_resolve_alert_type_and_title():
    assert resolve_close_alert_type("CLOSE_STOPLOSS", "防回吐保本平仓") == "CLOSE_STOPLOSS"
    assert resolve_close_alert_title("CLOSE_STOPLOSS", "防回吐保本平仓") == "防回吐保本 · 全平完成"
    assert resolve_close_alert_title("CLOSE_STOPLOSS", "触碰硬止损平仓") == "硬止损 · 全平完成"
    assert resolve_close_alert_title("CLOSE_TP3", "TP3完美收网") == "TP3平仓 · 雷达追踪收网"
    assert resolve_close_alert_type("CLOSE_TP3", None) == "CLOSE_TP3"
    assert resolve_close_alert_title("CLOSE_PROTECT", "风控拦截：xxx") == "风控拦截 · 保护全平"


def test_resolve_title_from_exchange_attribution():
    """Distinguish TP fill vs radar stop when no TV close_action."""
    tp_attr = {
        "close_origin": "exchange_limit_tp",
        "matched_tps": [1, 2],
        "human_reason": "盘口已平：限价止盈成交",
    }
    radar_attr = {
        "close_origin": "exchange_stop",
        "sl_kind": "CLOSE_SL_BREAKEVEN",
        "human_reason": "盘口已平：保本雷达/条件止损触发",
    }
    tp3_attr = {
        "close_origin": "radar_tp3_trail",
        "close_action_hint": "CLOSE_TP3",
        "human_reason": "TP3平仓（雷达追踪）",
    }
    assert resolve_close_alert_type(None, None, tp_attr) == "CLOSE_ATTRIBUTION"
    assert "限价止盈" in resolve_close_alert_title(None, None, tp_attr)
    assert "TP1,2" in resolve_close_alert_title(None, None, tp_attr)
    assert resolve_close_alert_type(None, None, radar_attr) == "CLOSE_SL_BREAKEVEN"
    assert "保本/移动" in resolve_close_alert_title(None, None, radar_attr)
    assert resolve_close_alert_type(None, None, tp3_attr) == "CLOSE_TP3"
    assert resolve_close_alert_title(None, None, tp3_attr) == "TP3平仓 · 雷达追踪收网"


def test_build_verify_note_with_delta():
    note = build_verify_note(
        exit_price=3500.0,
        live_pnl_pct=1.20,
        tv_pnl_pct=0.80,
        flat_confirmed=True,
    )
    assert "盘口已归零" in note
    assert "3500.00" in note
    assert "偏差 +0.40%" in note


def test_build_close_detail_full():
    tv = extract_tv_close_fields({
        "action": "CLOSE_TP3",
        "regime": 3,
        "atr": 30.0,
        "price": 3600.0,
        "side": "SHORT",
        "reason": "TP3完美收网",
        "pnl_pct": 2.5,
    })
    detail = build_close_detail(
        exchange_id="binance",
        side="SHORT",
        qty=0.05,
        entry=3500.0,
        regime=3,
        atr=30.0,
        exit_price=3600.0,
        pnl=5.0,
        funding_fee=0.01,
        tv_fields=tv,
        close_action="CLOSE_TP3",
        tv_reason="TP3完美收网",
        live_pnl_pct=2.86,
        verify_note="盘口已归零 | 平仓价 @3600.00",
        trade_id=42,
    )
    assert detail["close_subtype"] == "tp3"
    assert detail["regime"] == 3
    assert detail["tv_price"] == 3600.0
    assert detail["live_verified"] is True
    assert detail["trade_id"] == 42
    assert detail["pnl_pct_delta"] == 0.36
