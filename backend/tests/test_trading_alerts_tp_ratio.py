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
