"""Tests for TP ratio labels in DingTalk entry detail."""

from app.services.trading_alerts import (
    format_regime_radar_activation_legend,
    format_trading_alert_body,
    format_vps_entry_detail_cn,
    resolve_exchange_theme,
)


def test_format_regime_radar_activation_legend():
    legend = format_regime_radar_activation_legend()
    assert legend == "R1=50% · R2=60% · R3=70% · R4=80%"


def test_tv_open_dingtalk_shows_tv_leverage_not_config_25():
    """OPEN detail must carry TV leverage so DingTalk header is 5× not 25×."""
    detail = {
        "entry_type": "OPEN",
        "side": "LONG",
        "regime": 2,
        "qty": 0.96,
        "entry": 1892.43,
        "leverage": 5,
        "tv_leverage": 5,
        "risk_pct": 1.35,
        "qty_ratio": 1.0,
        "sl_distance": 14.09,
        "order_amount": 1816.73,
        "effective_leverage": 1.82,
        "sizing_mode": "tv_risk_formula",
        "tv_sl": 1878.34,
        "tv_tps": [1909.0, 1927.0, 1943.0],
        "radar_armed": False,
        "exchange": "binance",
        "symbol": "ETHUSDT",
    }
    body = format_vps_entry_detail_cn(detail, "binance")
    assert "TV杠杆" in body
    assert "5×" in body
    assert "等效杠杆" in body
    assert "1.82" in body
    assert "tv_risk_formula" in body
    theme = resolve_exchange_theme("binance", "ETHUSDT", leverage=5)
    assert theme["leverage"] == 5
    assert "5x" in theme["tag"]
    assert theme["tag"].startswith("#币安5x")
    alert = format_trading_alert_body(
        theme=theme,
        severity="info",
        alert_type="OPEN",
        title="开仓",
        message="test",
        user_id=1,
        uid="u1",
        display="t",
        detail=detail,
        exchange="binance",
    )
    assert "**5×**" in alert
    assert "**25×**" not in alert


def test_open_detail_shows_pine_tp_ratio_pct():
    body = format_vps_entry_detail_cn(
        {
            "entry_type": "OPEN",
            "side": "LONG",
            "regime": 1,
            "tp_ratios_pct": "25/35/40",
            "qty": 0.8,
            "entry": 2000.0,
            "leverage": 5,
        },
        "binance",
    )
    assert "止盈比例" in body
    assert "25/35/40" in body


def test_open_detail_radar_standby_until_tp1():
    body = format_vps_entry_detail_cn(
        {
            "entry_type": "OPEN",
            "side": "LONG",
            "regime": 4,
            "qty": 1.5,
            "entry": 1935.0,
            "radar_armed": False,
            "leverage": 5,
        },
        "binance",
    )
    assert "雷达状态" in body
    assert "TP1" in body
    assert "80%" in body  # R4 activation
    assert "50%" in body or "R1=50%" in body or "R4=80%" in body
    assert "85%" not in body


def test_open_detail_book_structure_and_tv_hard_sl():
    body = format_vps_entry_detail_cn(
        {
            "entry_type": "OPEN",
            "side": "SHORT",
            "regime": 1,
            "qty": 0.076,
            "entry": 1840.65,
            "leverage": 5,
            "tv_sl": 1844.34,
            "hard_sl_pct_display": "TV",
            "hard_sl_order_style": "stop_limit",
            "tv_sl_reference": 1844.34,
            "tv_tps": [1837.01, 1834.12, 1831.46],
            "atr": 4.44,
            "radar_armed": False,
            "radar_activation": 0.70,
            "radar_activation_effective": 0.95,
            "shield": {"order_style": "stop_limit"},
        },
        "binance",
    )
    assert "盘口结构" in body
    assert "基础单×3" in body
    assert "closePosition" in body or "条件委托" in body
    assert "TV硬止损" in body
    assert "1844.34" in body
    assert "已挂单" in body
    assert "仅参考" not in body
    assert "开仓价×" not in body
    assert "VPS 硬止损" not in body
    assert "雷达触发价" in body or "50%" in body or "条件委托" in body
    assert "条件委托" in body
    assert "只前进" in body or "R1=50%" in body
    assert "85%" not in body
