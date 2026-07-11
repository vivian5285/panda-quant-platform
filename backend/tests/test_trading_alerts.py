"""Tests for GEMINI per-exchange DingTalk themes and admin-readable Chinese alerts."""

from app.services.trading_alerts import (
    EXCHANGE_THEMES,
    format_admin_detail_lines,
    format_trading_alert_body,
    resolve_exchange_theme,
    should_push_trading_dingtalk,
)


def test_binance_theme_20x():
    theme = resolve_exchange_theme("binance")
    assert theme["leverage"] == 20
    assert theme["tag"] == "#币安20x"
    assert "GEMINI量化" in theme["brand"]
    assert "黄金" not in theme["brand"]


def test_all_exchanges_20x_leverage():
    for key in ("binance", "deepcoin", "okx", "gate"):
        assert resolve_exchange_theme(key)["leverage"] == 20


def test_exchange_themes_distinct_palettes():
    palettes = {EXCHANGE_THEMES[k]["palette"] for k in EXCHANGE_THEMES}
    assert len(palettes) == 4


def test_resolve_gateio_alias():
    assert resolve_exchange_theme("gateio")["tag"] == "#Gate20x"


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
    assert "#OKX20x" in body
    assert "20×" in body
    assert "ETH-USDT-SWAP" in body


def test_should_push_open_but_not_trail():
    assert should_push_trading_dingtalk("OPEN", "info") is True
    assert should_push_trading_dingtalk("TRAIL", "info") is False


def test_should_push_cap_align_to_admin():
    assert should_push_trading_dingtalk("CAP_ALIGN", "critical") is True
    assert should_push_trading_dingtalk("CAP_ALIGN_BLOCKED", "critical") is True


def test_cap_align_detail_chinese_readable_no_json():
    detail = {
        "exchange": "binance",
        "side": "LONG",
        "regime": 3,
        "margin_pct": 0.35,
        "initial_principal": 755.0,
        "equity_balance": 755.0,
        "margin_usd": 264.25,
        "live_qty": 2.954,
        "target_qty": 1.489,
        "trimmed": 1.465,
        "new_qty": 1.489,
        "trigger": "重启恢复",
        "defense": {"matched": 3, "expected": 3},
        "radar_sl_preserved": 1775.0,
    }
    block = format_admin_detail_lines("CAP_ALIGN", detail, exchange="binance")
    assert "本金快照" in block
    assert "755.00 USDT" in block
    assert "2.954" in block
    assert "1.489" in block
    assert "做多" in block
    assert "R3" in block
    assert "```" not in block

    body = format_trading_alert_body(
        theme=resolve_exchange_theme("binance"),
        severity="critical",
        alert_type="CAP_ALIGN",
        title="叠仓超标 · 雷达强制对齐",
        message="【R3档位】实盘 2.954ETH 超过本金比例上限 1.489ETH",
        user_id=6,
        uid="39210066",
        display="测试用户",
        detail=detail,
        exchange="binance",
    )
    assert "核实明细" in body
    assert "币安" in body
    assert "```" not in body
    assert "json" not in body.lower()


def test_all_gemini_exchanges_share_principal_cap_guard():
    """币安/OKX/Gate 共用 PositionSupervisor；深币共用同一套 cap mixin."""
    from unittest.mock import MagicMock

    from app.core.exchange_factory import create_supervisor
    from app.core.position_supervisor import PositionSupervisor
    from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
    from app.models import ExchangeType, User

    for ex in (ExchangeType.BINANCE, ExchangeType.OKX, ExchangeType.GATE):
        user = User(id=1, exchange=ex.value, initial_principal=700.0)
        client = MagicMock()
        client.exchange_id = ex.value
        client.trading_symbol = "ETHUSDT"
        client.trading_leverage = 15
        client.get_futures_account_summary.return_value = {
            "total_margin_balance": 700.0,
            "available_balance": 12.0,
        }
        sup = create_supervisor(user, client)
        assert isinstance(sup, PositionSupervisor)
        assert sup.exchange_id == ex.value
        max_qty, meta = sup._compute_regime_cap_target(1775.0)
        assert meta["sizing_base"] == 700.0
        assert max_qty > 0.5

    user = User(id=2, exchange=ExchangeType.DEEPCOIN.value, initial_principal=700.0)
    dc = MagicMock()
    dc.get_futures_account_summary.return_value = {
        "total_margin_balance": 700.0,
        "available_balance": 15.0,
    }
    from unittest.mock import patch

    with patch.object(DeepcoinPositionSupervisor, "_start_idle_flat_patrol"), patch.object(
        DeepcoinPositionSupervisor, "_start_signal_worker"
    ):
        dc_sup = create_supervisor(user, dc)
    assert isinstance(dc_sup, DeepcoinPositionSupervisor)
    max_c, meta_c = dc_sup._compute_regime_cap_target(3000.0)
    assert meta_c["sizing_base"] == 700.0
    assert max_c >= 1
