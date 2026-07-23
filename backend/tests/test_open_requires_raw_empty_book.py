"""Open gate must see RAW leftover LIMITs (ghost orders), not only filtered TP/stop."""

import unittest
from unittest.mock import MagicMock, patch

from app.core.position_supervisor import PositionSupervisor


def _sup():
    client = MagicMock()
    client.get_open_orders.return_value = []
    client.cancel_all_open_orders.return_value = {"leftover": 0, "errors": []}
    client.trading_symbol = "XAUUSDT"
    client.exchange_id = "binance"
    sup = PositionSupervisor(user_id=6, client=client, initial_principal=1000.0)
    sup.symbol = "XAUUSDT"
    sup.exchange_id = "binance"
    sup._purge_defense_orders_on_flat = MagicMock(return_value={"leftover_orders": 0})
    sup._cancel_all_verified = MagicMock(return_value={"ok": True, "remaining": 0})
    sup._disarm_adverse_staged_stops = MagicMock(return_value={"cancelled": 0})
    sup._reset_adverse_radar = MagicMock()
    sup._save_state = MagicMock()
    sup._alert = MagicMock()
    sup._log = MagicMock()
    return sup, client


class TestOpenRequiresRawEmptyBook(unittest.TestCase):
    def test_raw_count_sees_ghost_limit_not_matching_tp_filter(self):
        sup, client = _sup()
        ghost = {
            "orderId": 777,
            "type": "LIMIT",
            "side": "SELL",
            "price": "4162.0",
            "origQty": "0.01",
            "reduceOnly": False,
        }
        client.get_open_orders.return_value = [ghost]
        self.assertEqual(sup._count_raw_exchange_orders(), 1)
        with patch.object(sup, "_collect_tp_limit_orders", return_value=[]):
            with patch.object(sup, "_collect_adverse_stop_orders", return_value=[]):
                self.assertEqual(sup._count_open_book_orders(), 0)

    def test_ensure_book_clean_aborts_when_ghost_limit_survives(self):
        sup, client = _sup()
        ghost = {
            "orderId": 777,
            "type": "LIMIT",
            "side": "SELL",
            "price": "4162.0",
            "origQty": "0.01",
            "reduceOnly": False,
        }
        client.cancel_all_open_orders.return_value = {"leftover": 0, "errors": []}
        client.get_open_orders.return_value = [ghost]
        with patch("app.core.position_supervisor.time.sleep", return_value=None):
            with patch.object(sup, "_collect_tp_limit_orders", return_value=[]):
                with patch.object(sup, "_collect_adverse_stop_orders", return_value=[]):
                    detail = sup._ensure_book_clean_before_open("test_ghost")
        self.assertFalse(detail["ok"])
        self.assertEqual(detail["raw_after"], 1)

    def test_ensure_book_clean_ok_when_raw_empty(self):
        sup, client = _sup()
        client.get_open_orders.return_value = []
        client.cancel_all_open_orders.return_value = {"leftover": 0, "errors": []}
        with patch("app.core.position_supervisor.time.sleep", return_value=None):
            detail = sup._ensure_book_clean_before_open("test_clean")
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["raw_after"], 0)


if __name__ == "__main__":
    unittest.main()
