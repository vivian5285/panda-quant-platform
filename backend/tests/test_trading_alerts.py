"""Tests for GEMINI per-exchange DingTalk themes and 10x leverage labels."""

from app.services.trading_alerts import (
    EXCHANGE_THEMES,
    format_trading_alert_body,
    resolve_exchange_theme,
    should_push_trading_dingtalk,
)


def test_binance_theme_10x():
    theme = resolve_exchange_theme("binance")
    assert theme["leverage"] == 10
    assert theme["tag"] == "#币安10x"
    assert "GEMINI量化" in theme["brand"]
    assert "黄金" not in theme["brand"]


def test_all_exchanges_10x_leverage():
    for key in ("binance", "deepcoin", "okx", "gate"):
        assert EXCHANGE_THEMES[key]["leverage"] == 10


def test_exchange_themes_distinct_palettes():
    palettes = {EXCHANGE_THEMES[k]["palette"] for k in EXCHANGE_THEMES}
    assert len(palettes) == 4


def test_resolve_gateio_alias():
    assert resolve_exchange_theme("gateio")["tag"] == "#Gate10x"


def test_alert_body_includes_gemini_header_and_exchange_accent():
    theme = resolve_exchange_theme("okx")
    body = format_trading_alert_body(
        theme=theme,
        severity="info",
        alert_type="OPEN",
        title="开仓",
        message="LONG 0.5 ETH",
        user_id=1,
        uid="U001",
        display="test@example.com",
    )
    assert "GEMINI量化 · OKX" in body
    assert "#OKX10x" in body
    assert "10×" in body
    assert "紫罗兰" in body


def test_should_push_open_but_not_trail():
    assert should_push_trading_dingtalk("OPEN", "info") is True
    assert should_push_trading_dingtalk("TRAIL", "info") is False
