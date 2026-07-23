"""Anti-stack: live stop count must be unfiltered; unknown book refuses place."""

import unittest
from unittest.mock import MagicMock, patch

from app.core.adverse_radar_guard import AdverseRadarMixin, _is_stop_market_like


class _Host(AdverseRadarMixin):
    def __init__(self):
        self.user_id = 6
        self.symbol = "ETHUSDT"
        self.canonical_symbol = "ETHUSDT"
        self.exchange_id = "binance"
        self.current_side = "LONG"
        self.client = MagicMock()
        self._pending_adverse_algo_ids = []
        self.current_sl = 1895.42
        self.tv_sl = 1895.42
        self._last_hard_sl_order_style = None


class TestStopAntiStack(unittest.TestCase):
    def test_is_stop_market_like_recognizes_algo_stop(self):
        self.assertTrue(_is_stop_market_like({"type": "STOP_MARKET", "stopPrice": "1895.42"}))
        self.assertTrue(_is_stop_market_like({
            "type": "STOP", "isAlgoOrder": True, "triggerPrice": "1895.42", "stopPrice": "1895.42",
        }))

    def test_count_live_stops_unfiltered_same_price_stack(self):
        host = _Host()
        stops = [
            {
                "algoId": 1000 + i,
                "type": "STOP_MARKET",
                "side": "SELL",
                "stopPrice": "1895.42",
                "isAlgoOrder": True,
            }
            for i in range(5)
        ]
        host.client.get_open_orders.return_value = stops
        host.client.get_open_algo_orders.return_value = []
        self.assertEqual(host._count_live_stop_orders(), 5)

    def test_place_refuses_when_book_fetch_unknown(self):
        host = _Host()
        with patch.object(host, "_count_live_stop_orders", return_value=-1):
            ok = host._place_adverse_stop_slice(1895.42, 0.03)
        self.assertFalse(ok)
        self.assertEqual(host._last_hard_sl_order_style, "refused_book_unknown")
        host.client.place_stop_market_order.assert_not_called()

    def test_place_skips_when_already_live(self):
        host = _Host()
        with patch.object(host, "_count_live_stop_orders", return_value=1):
            with patch.object(host, "_hard_stop_on_book", return_value=True):
                ok = host._place_adverse_stop_slice(1895.42, 0.03)
        self.assertTrue(ok)
        self.assertEqual(host._last_hard_sl_order_style, "skipped_already_live")
        host.client.place_stop_market_order.assert_not_called()

    def test_place_refuses_when_hard_book_unread(self):
        host = _Host()
        with patch.object(host, "_count_live_stop_orders", return_value=1):
            with patch.object(host, "_hard_stop_on_book", return_value=None):
                ok = host._place_adverse_stop_slice(1895.42, 0.03)
        self.assertFalse(ok)
        self.assertEqual(host._last_hard_sl_order_style, "refused_book_unknown")
        host.client.place_stop_market_order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
