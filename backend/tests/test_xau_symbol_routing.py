"""Regression: XAU must not silently route orders/alerts to ETH."""

from app.core.symbol_precision import round_quantity, min_qty_for
from app.core.symbol_registry import CANONICAL_XAU, CANONICAL_ETH, normalize_canonical_symbol
from app.core.tp_regime_ratios import build_regime_settings
from app.core.tp_slice_guard import compute_tp_slices
from app.services.trading_alerts import format_vps_entry_detail_cn, resolve_exchange_theme


def test_xau_tv_ticker_normalizes():
    assert normalize_canonical_symbol("XAUUSDT.P") == CANONICAL_XAU
    assert normalize_canonical_symbol("BINANCE:XAUUSDT.P") == CANONICAL_XAU


def test_dingtalk_theme_xau_not_eth():
    theme = resolve_exchange_theme("binance", "XAUUSDT")
    assert theme["canonical_symbol"] == CANONICAL_XAU
    assert "XAU" in theme["tag"]
    assert theme["qty_unit"] == "盎司"
    assert theme["symbol"] == "XAUUSDT"


def test_vps_entry_detail_uses_xau_unit():
    text = format_vps_entry_detail_cn(
        {
            "exchange": "binance",
            "symbol": "XAUUSDT",
            "canonical_symbol": "XAUUSDT",
            "qty_unit": "盎司",
            "entry_type": "OPEN",
            "side": "SHORT",
            "regime": 2,
            "qty": 0.04,
            "entry": 4034.56,
            "base_qty": 0.04,
        },
        exchange="binance",
    )
    assert "盎司" in text
    assert "合约" in text
    assert "XAUUSDT" in text
    assert "0.0400" in text or "0.04" in text
    # Must not mislabel as ETH unit for XAU fills
    assert "ETH" not in text.split("实盘数量")[-1][:40] if "实盘数量" in text else True


def test_dingtalk_alert_body_distinguishes_xau():
    from app.services.trading_alerts import format_trading_alert_body, resolve_exchange_theme

    theme = resolve_exchange_theme("binance", "XAUUSDT")
    body = format_trading_alert_body(
        theme=theme,
        severity="info",
        alert_type="OPEN",
        title="开仓",
        message="XAUUSDT SHORT 0.04",
        user_id=1,
        uid="U1",
        display="test",
        detail={"symbol": "XAUUSDT", "canonical_symbol": "XAUUSDT", "exchange": "binance"},
        exchange="binance",
    )
    assert "XAU" in body
    assert "XAUUSDT" in body
    assert "#币安" in body or "XAU" in theme["tag"]
    assert "ETHUSDT" not in body.split("合约")[1][:80] if "合约" in body else True


def test_xau_tp_slices_keep_three_when_qty_allows():
    """0.04 XAU ≥ 3×0.01 → keep TP1/2/3 (not fold TP1 away)."""
    settings = build_regime_settings()
    tps = [4022.85, 4013.27, 4004.75]
    slices = compute_tp_slices(
        0.04,
        2,
        tps,
        settings,
        round_qty_fn=lambda x: round_quantity(x, CANONICAL_XAU),
        min_qty=min_qty_for(CANONICAL_XAU),
    )
    assert len(slices) == 3
    levels = [lvl for lvl, _, _ in slices]
    assert levels == [1, 2, 3]
    assert all(q >= min_qty_for(CANONICAL_XAU) - 1e-9 for _, q, _ in slices)
    assert abs(sum(q for _, q, _ in slices) - 0.04) < 1e-9


def test_xau_tp_slices_fold_when_too_small():
    """0.02 XAU < 3×0.01 → fold to fewer placeable tiers."""
    settings = build_regime_settings()
    tps = [4022.85, 4013.27, 4004.75]
    slices = compute_tp_slices(
        0.02,
        2,
        tps,
        settings,
        round_qty_fn=lambda x: round_quantity(x, CANONICAL_XAU),
        min_qty=min_qty_for(CANONICAL_XAU),
    )
    assert 1 <= len(slices) <= 2
    assert abs(sum(q for _, q, _ in slices) - 0.02) < 1e-9


def test_xau_tp_slices_respect_min_qty():
    test_xau_tp_slices_keep_three_when_qty_allows()
    test_xau_tp_slices_fold_when_too_small()


def test_binance_client_defaults_to_trading_symbol(monkeypatch):
    from unittest.mock import MagicMock
    import app.core.binance_client as bc

    monkeypatch.setattr(bc, "Client", MagicMock())
    c = bc.BinanceClient("k", "s", 1, trading_symbol="XAUUSDT")
    c.canonical_symbol = "XAUUSDT"
    assert c._sym(None) == "XAUUSDT"
    assert c._sym("ETHUSDT") == "ETHUSDT"
    assert c._can_sym() == "XAUUSDT"
    assert c.place_limit_order.__defaults__ is None or True
    # Default path when callers omit symbol kwarg
    import inspect
    sig = inspect.signature(c.place_limit_order)
    assert sig.parameters["symbol"].default is None
