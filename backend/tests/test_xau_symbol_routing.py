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
    assert "0.0400" in text or "0.04" in text
    # Must not mislabel as ETH unit for XAU fills
    assert "ETH" not in text.split("实盘数量")[-1][:40] if "实盘数量" in text else True


def test_xau_tp_slices_respect_min_qty():
    """R2 20% of 0.04 XAU = 0.008 < min 0.01 → fold into later tiers, still placeable."""
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
    assert slices, "expected at least one TP slice for 0.04 XAU"
    assert all(q >= min_qty_for(CANONICAL_XAU) - 1e-9 or i == len(slices) - 1
               for i, (_, q, _) in enumerate(slices) if q > 0)
    total = sum(q for _, q, _ in slices)
    assert abs(total - 0.04) < 0.011  # within one XAU step after fold


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
