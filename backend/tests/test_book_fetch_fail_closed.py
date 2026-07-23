"""FAIL CLOSED: book fetch errors must never look like an empty book."""

import unittest
from unittest.mock import MagicMock, patch

from app.core.binance_client import BinanceClient, BookFetchError


class TestBookFetchFailClosed(unittest.TestCase):
    def _client(self):
        bc = BinanceClient.__new__(BinanceClient)
        bc.client = MagicMock()
        bc.user_id = 6
        bc.default_symbol = "ETHUSDT"
        bc._book_cache = None
        bc._book_cache_ts = 0.0
        bc._trading_symbols = MagicMock(return_value=["ETHUSDT"])
        bc._sym = lambda s=None: s or "ETHUSDT"
        bc._invalidate_book_cache = MagicMock()
        bc._parse_algo_order_rows = lambda raw: raw if isinstance(raw, list) else []
        bc._normalize_algo_order = lambda row: row
        return bc

    def test_get_open_orders_raises_on_regular_fetch_fail(self):
        bc = self._client()
        with patch("app.core.rest_book_cache.get_cached_open_orders", side_effect=RuntimeError("ban")):
            with self.assertRaises(BookFetchError):
                bc.get_open_orders("ETHUSDT")

    def test_get_open_algo_orders_raises_on_symbol_fail(self):
        bc = self._client()
        bc.client._request_futures_api = MagicMock(side_effect=RuntimeError("ban"))
        with patch("app.core.rest_book_cache.get_cached_algo_orders", side_effect=lambda **kw: kw["fetch_for_symbols"](["ETHUSDT"])):
            with self.assertRaises(BookFetchError):
                bc.get_open_algo_orders("ETHUSDT")

    def test_mop_returns_minus_one_when_list_fails(self):
        bc = self._client()
        bc.client.futures_get_open_orders = MagicMock(side_effect=RuntimeError("ban"))
        bc.get_open_algo_orders = MagicMock(side_effect=BookFetchError("algo"))
        with patch("app.core.binance_client.time.sleep", return_value=None):
            left = bc._mop_up_leftover_orders("ETHUSDT", rounds=1)
        self.assertEqual(left, -1)


if __name__ == "__main__":
    unittest.main()
