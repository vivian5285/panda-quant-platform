"""Regression: rebuild TP must not stack duplicates when book already has matching limits."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.binance_smart_defense import BinanceSmartDefenseMixin
from app.core.tp_defense_reconcile import tp_price_matches


class _Host(BinanceSmartDefenseMixin):
    exchange_id = "binance"
    user_id = 6
    symbol = "ETHUSDT"
    current_side = "LONG"
    watched_entry = 1918.0
    watched_qty = 0.033
    initial_qty = 0.033
    tv_tps = [1925.97, 1940.78, 1955.58]
    regime = 3
    regime_settings = {
        3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
    }
    consumed_tp_levels = []
    best_price = 1918.0

    def __init__(self):
        self.client = MagicMock()
        self._logs = []
        self._open = []

    def _def_log(self, msg, level=None):
        self._logs.append(str(msg))

    def _save_state(self):
        pass

    def _resolve_live_qty(self, q):
        return float(q or self.watched_qty)

    def _current_tp_price(self):
        return 1910.0  # below both TPs so not past

    def _sync_consumed_tp_levels(self, *a, **k):
        pass

    def _cancel_tp_orders_for_consumed_levels(self):
        return 0

    def _collect_tp_limit_orders(self):
        out = []
        for o in self._open:
            if str(o.get("type", "")).upper() != "LIMIT":
                continue
            out.append({
                "orderId": o["orderId"],
                "price": float(o["price"]),
                "qty": float(o["origQty"]),
                "side": o.get("side", "SELL"),
            })
        return out

    def _open_tp_prices_on_book(self):
        return [float(o["price"]) for o in self._collect_tp_limit_orders()]

    def _expected_tp_levels(self, live_qty, curr_px=None):
        # Simplified two-tier like live (TP3 not hung as limit)
        from app.core.tp_slice_guard import compute_tp_slices
        slices = compute_tp_slices(
            float(live_qty), self.regime, self.tv_tps, self.regime_settings, exclude_levels={3},
        )
        return [{"level": lv, "qty": q, "price": px} for lv, q, px in slices]

    def _consumed_tp_level_set(self):
        return set(self.consumed_tp_levels or [])

    def _tp_price_tol(self):
        return 0.05

    def _mark_tp_placed(self, level, order_id=None):
        pass


def test_rebuild_tp_skips_when_matching_limits_already_on_book():
    h = _Host()
    # Seed exact TP1+TP2 already on book (the duplicate bug scenario's "first hang")
    h._open = [
        {"orderId": 101, "type": "LIMIT", "side": "SELL", "price": "1925.97", "origQty": "0.016"},
        {"orderId": 102, "type": "LIMIT", "side": "SELL", "price": "1940.78", "origQty": "0.017"},
    ]
    # Patch expected levels to match seed qtys
    h._expected_tp_levels = lambda live_qty, curr_px=None: [
        {"level": 1, "qty": 0.016, "price": 1925.97},
        {"level": 2, "qty": 0.017, "price": 1940.78},
    ]
    h.client.place_limit_order = MagicMock(return_value={"orderId": 999})
    h.client.cancel_order = MagicMock()

    placed = h._rebuild_tp_limit_orders(0.033, 1918.0)
    assert placed == 0
    h.client.place_limit_order.assert_not_called()
    assert any("已存在" in m and "防重复挂单" in m for m in h._logs)


def test_rebuild_tp_purges_duplicates_before_place():
    h = _Host()
    h._open = [
        {"orderId": 201, "type": "LIMIT", "side": "SELL", "price": "1925.97", "origQty": "0.016"},
        {"orderId": 202, "type": "LIMIT", "side": "SELL", "price": "1925.97", "origQty": "0.016"},
        {"orderId": 203, "type": "LIMIT", "side": "SELL", "price": "1940.78", "origQty": "0.017"},
        {"orderId": 204, "type": "LIMIT", "side": "SELL", "price": "1940.78", "origQty": "0.017"},
    ]
    h._expected_tp_levels = lambda live_qty, curr_px=None: [
        {"level": 1, "qty": 0.016, "price": 1925.97},
        {"level": 2, "qty": 0.017, "price": 1940.78},
    ]

    def _cancel(symbol, oid):
        h._open = [o for o in h._open if int(o["orderId"]) != int(oid)]

    h.client.cancel_order.side_effect = _cancel
    h.client.place_limit_order = MagicMock(return_value={"orderId": 999})

    # After purge, one of each price remains matching → rebuild should place 0
    placed = h._rebuild_tp_limit_orders(0.033, 1918.0)
    assert h.client.cancel_order.call_count >= 2  # at least one cancel per duplicated price
    assert placed == 0
    h.client.place_limit_order.assert_not_called()
    # Exactly one order per TP price left
    prices = [float(o["price"]) for o in h._open]
    assert prices.count(1925.97) == 1
    assert prices.count(1940.78) == 1
