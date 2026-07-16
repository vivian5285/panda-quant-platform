"""Tests for multi-exchange ETH fill normalization and PnL summing."""

from app.services.exchange_fill_sync import (
    normalize_fill_row,
    sum_realized_from_fills,
    trading_symbol_for_exchange,
)


def test_symbols_per_exchange():
    assert trading_symbol_for_exchange("binance") == "ETHUSDT"
    assert trading_symbol_for_exchange("binance", "XAUUSDT") == "XAUUSDT"
    assert "ETH" in trading_symbol_for_exchange("okx")
    assert "XAU" in trading_symbol_for_exchange("okx", "XAUUSDT")
    assert "ETH" in trading_symbol_for_exchange("gate")
    assert "ETH" in trading_symbol_for_exchange("deepcoin")


def test_normalize_binance_fill():
    n = normalize_fill_row("binance", {
        "id": 123,
        "side": "SELL",
        "qty": "0.1",
        "price": "3500",
        "realizedPnl": "-1.25",
        "commission": "0.01",
        "time": 1700000000000,
        "symbol": "ETHUSDT",
    })
    assert n["fill_id"] == "123"
    assert n["realized_pnl"] == -1.25
    assert n["commission"] == 0.01


def test_normalize_okx_fill():
    n = normalize_fill_row("okx", {
        "tradeId": "t1",
        "fillSz": "1",
        "fillPx": "3500",
        "fillPnl": "2.5",
        "fee": "-0.02",
        "ts": "1700000000000",
        "side": "sell",
        "instId": "ETH-USDT-SWAP",
    })
    assert n["realized_pnl"] == 2.5
    assert n["commission"] == 0.02


def test_normalize_gate_position_close():
    n = normalize_fill_row("gate", {
        "time": 1700000000,
        "pnl": "-3.5",
        "side": "long",
        "contract": "ETH_USDT",
        "raw_kind": "position_close",
    })
    assert n["realized_pnl"] == -3.5
    assert n["raw_kind"] == "position_close"


def test_sum_realized_filters_window():
    fills = [
        {"realized_pnl": 1.0, "time_ms": 1000},
        {"realized_pnl": 2.0, "time_ms": 2000},
        {"realized_pnl": -0.5, "time_ms": 3000},
    ]
    assert sum_realized_from_fills(fills, start_ms=1500, end_ms=2500) == 2.0
    assert sum_realized_from_fills(fills) == 2.5
