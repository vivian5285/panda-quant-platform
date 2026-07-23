#!/usr/bin/env python3
"""Unit coverage: cancel_all must mop leftovers when bulk cancel is partial."""

from unittest.mock import MagicMock

from app.core.binance_client import BinanceClient


def test_cancel_all_open_orders_mops_leftover_limit():
    client = MagicMock()
    # Bulk cancel "succeeds" but leaves one LIMIT; mop cancels it on round 1.
    leftover = {
        "orderId": 999001,
        "type": "LIMIT",
        "side": "SELL",
        "price": "4800.5",
        "origQty": "0.01",
        "reduceOnly": True,
    }
    client.futures_get_open_orders.side_effect = [[leftover], []]
    client._request_futures_api = MagicMock(return_value={})
    client.futures_cancel_all_open_orders = MagicMock(return_value={})
    client.futures_cancel_order = MagicMock(return_value={})

    bc = BinanceClient.__new__(BinanceClient)
    bc.client = client
    bc.user_id = 6
    bc.default_symbol = "XAUUSDT"
    bc._book_cache = None
    bc._book_cache_ts = 0.0
    bc.get_open_algo_orders = MagicMock(return_value=[])

    meta = bc.cancel_all_open_orders("XAUUSDT")
    assert isinstance(meta, dict)
    assert meta["leftover"] == 0
    client.futures_cancel_all_open_orders.assert_called()
    client.futures_cancel_order.assert_called()
