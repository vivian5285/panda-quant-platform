"""Tests for 妈妈版 DingTalk entry / close short templates."""

from app.services.trading_alerts import (
    format_regime_radar_activation_legend,
    format_trading_alert_body,
    format_vps_entry_detail_cn,
    resolve_exchange_theme,
)
from app.services.close_alert_utils import resolve_close_alert_title


FORBIDDEN_KEYWORDS = (
    "极限逃顶", "极限逃底", "风控拦截", "降维打击", "复利保卫战",
    "极速逃脱", "敏锐防守", "高优拦截", "动能衰竭", "变盘规避",
    "大周期破位", "常规防守", "时间止损", "裸K反转", "加仓", "首仓", "多档位",
)


def test_format_regime_radar_activation_legend():
    legend = format_regime_radar_activation_legend()
    assert "硬止损呼吸垫固定1.15" in legend
    assert "弱/中/强" in legend
    assert "TP1+TP2" in legend or "雷达启动" in legend
    assert "重入仅强趋势" in legend


def test_open_detail_includes_trend_tier_label():
    body = format_vps_entry_detail_cn(
        {
            "side": "LONG",
            "qty": 0.3,
            "entry": 3300.0,
            "initial_stop": 3240.0,
            "equity": 1000,
            "tier_label": "强趋势",
            "trend_tier": 2,
            "tv_tps": [3350.0, 3400.0],
        },
        "binance",
    )
    assert "档位·强趋势" in body
    assert "TP 3350.00/3400.00" in body


def test_tv_open_dingtalk_shows_tv_leverage_not_config_25():
    detail = {
        "entry_type": "OPEN",
        "side": "LONG",
        "qty": 0.303,
        "entry": 3300.0,
        "leverage": 5,
        "equity": 1000,
        "initial_stop": 3240.0,
        "exchange": "binance",
        "symbol": "ETHUSDT",
    }
    body = format_vps_entry_detail_cn(detail, "binance")
    assert "开仓 做多" in body
    assert "3300.00" in body
    assert "0.3030" in body
    assert "3240.00" in body
    assert "1000.00" in body
    for kw in FORBIDDEN_KEYWORDS:
        assert kw not in body


def test_open_detail_shows_mom_template():
    body = format_vps_entry_detail_cn(
        {
            "side": "LONG",
            "qty": 0.8,
            "entry": 2000.0,
            "initial_stop": 1940.0,
            "equity": 1000,
        },
        "binance",
    )
    assert body.startswith("开仓")
    assert "初始止损" in body
    assert "账户权益" in body


def test_open_detail_no_legacy_radar_words():
    body = format_vps_entry_detail_cn(
        {
            "side": "SHORT",
            "qty": 0.076,
            "entry": 1840.65,
            "initial_stop": 1844.34,
            "equity": 500,
        },
        "binance",
    )
    assert "激活85%" not in body
    assert "雷达" not in body
    for kw in FORBIDDEN_KEYWORDS:
        assert kw not in body


def test_close_titles_mom_style():
    assert resolve_close_alert_title("CLOSE_QUICK_EXIT", "评分反转") == "反转保护（快速退出）"
    assert "风控拦截" not in resolve_close_alert_title("CLOSE_PROTECT", "风控拦截：xxx")
    # breakeven_phase=True = radar in adaptive tracking mode
    t1 = resolve_close_alert_title(
        "CLOSE_BREATH_STOP", "止损平仓", {"breakeven_phase": False},
    )
    assert "自适应追踪止损" not in t1  # not radar-activated
    # breakeven_phase=True = adaptive tracking active
    t2 = resolve_close_alert_title(
        "CLOSE_BREATH_STOP", "", {"breakeven_phase": True},
    )
    assert "自适应追踪止损平仓（雷达激活）" == t2


def test_alert_body_open_uses_short_detail():
    theme = resolve_exchange_theme("binance", "ETHUSDT", leverage=5)
    detail = {
        "side": "LONG",
        "qty": 0.3,
        "entry": 3300,
        "initial_stop": 3240,
        "equity": 1000,
        "exchange": "binance",
    }
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
    assert "开仓 做多" in alert
    assert "**25×**" not in alert
