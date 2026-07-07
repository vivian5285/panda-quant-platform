"""Tests for VPS restart TP reconciliation (exchange-first)."""

from unittest.mock import MagicMock

import pytest

from app.core.binance_smart_defense import BinanceSmartDefenseMixin
from app.core.tp_defense_reconcile import (
    tp_price_matches,
    tp_qty_matches,
)


class _Probe(BinanceSmartDefenseMixin):
    def __init__(self, orders, position_qty=1.251):
        self.user_id = 6
        self.symbol = "ETHUSDT"
        self.current_side = "LONG"
        self.tv_tps = [1832.37, 1855.03, 1875.96]
        self.regime = 3
        self.regime_settings = {3: {"ratios": [0.18, 0.32, 0.5]}}
        self.watched_qty = position_qty
        self.watched_entry = 1809.97
        self.current_sl = 1809.97
        self._orders = list(orders)
        self.client = MagicMock()
        self.client.get_open_orders.side_effect = lambda _sym: list(self._orders)

        def _cancel(_sym, oid):
            self._orders = [o for o in self._orders if o.get("orderId") != oid]
            return True

        self.client.cancel_order.side_effect = _cancel
        self.client.place_limit_order.return_value = {"orderId": 999}

    def _get_active_position(self):
        return {"size": self.watched_qty}

    def _save_state(self):
        pass


def _tp_order(oid, price, qty, reduce_only=True):
    return {
        "orderId": oid,
        "type": "LIMIT",
        "side": "SELL",
        "price": str(price),
        "origQty": str(qty),
        "reduceOnly": reduce_only,
    }


def test_tp_price_matches_tight_tick():
    assert tp_price_matches(1832.37, 1832.38)
    assert not tp_price_matches(1832.37, 1831.0)


def test_startup_reconcile_skips_when_three_tps_aligned():
    qty = 1.251
    q1, q2, q3 = 0.225, 0.4, 0.626
    probe = _Probe([
        _tp_order(1, 1832.37, q1),
        _tp_order(2, 1855.03, q2),
        _tp_order(3, 1875.96, q3),
    ], position_qty=qty)
    result = probe._reconcile_tp_defenses_on_startup(qty, 1809.97)
    assert result["skipped"] is True
    assert result["matched"] == 3
    probe.client.place_limit_order.assert_not_called()
    probe.client.cancel_order.assert_not_called()


def test_startup_reconcile_purges_duplicate_keeps_best_qty():
    qty = 1.251
    probe = _Probe([
        _tp_order(1, 1832.37, 0.225),
        _tp_order(2, 1832.37, 0.1),
        _tp_order(3, 1855.03, 0.4),
        _tp_order(4, 1875.96, 0.626),
    ], position_qty=qty)
    result = probe._reconcile_tp_defenses_on_startup(qty, 1809.97)
    assert result["matched"] == 3
    assert probe.client.cancel_order.call_count == 1
    probe.client.place_limit_order.assert_not_called()


def test_is_tp_limit_order_ignores_adverse_stop_at_wrong_price():
    probe = _Probe([])
    adverse = {
        "orderId": 10,
        "type": "LIMIT",
        "side": "SELL",
        "price": "1755.00",
        "origQty": "1.251",
        "reduceOnly": False,
    }
    assert probe._is_tp_limit_order(adverse) is False


def test_qty_matches_uses_relative_tolerance():
    assert tp_qty_matches(0.626, 0.625, 1.251)
    assert not tp_qty_matches(0.626, 0.001, 1.251)
