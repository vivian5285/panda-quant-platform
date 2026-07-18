"""Tests for TP ratio labels in DingTalk entry detail."""

from app.services.trading_alerts import format_vps_entry_detail_cn


def test_open_detail_shows_pine_tp_ratio_pct():
    body = format_vps_entry_detail_cn(
        {
            "entry_type": "OPEN",
            "side": "LONG",
            "regime": 1,
            "tp_ratios_pct": "25/35/40",
            "qty": 0.8,
            "entry": 2000.0,
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
        },
        "binance",
    )
    assert "雷达状态" in body
    assert "TP1" in body
    assert "85%" in body


def test_open_detail_book_structure_and_tv_sl_reference_only():
    body = format_vps_entry_detail_cn(
        {
            "entry_type": "OPEN",
            "side": "SHORT",
            "regime": 1,
            "qty": 0.076,
            "entry": 1840.65,
            "tv_sl": 1891.82,
            "hard_sl_pct_display": "2.8%",
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
    assert "Stop-Limit" in body
    assert "仅参考" in body
    assert "1844.34" in body
    assert "雷达触发价" in body
    assert "条件委托" in body
