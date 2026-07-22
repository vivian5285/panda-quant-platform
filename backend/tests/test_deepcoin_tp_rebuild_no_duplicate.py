"""DeepCoin regression: _rebuild_defenses must not stack TP limits already on book."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor
from app.core.tp_defense_reconcile import tp_price_matches


class _DcHost:
    """Minimal host binding DeepCoin rebuild/dedupe helpers."""

    exchange_id = "deepcoin"
    user_id = 1
    symbol = "ETH-USDT-SWAP"
    current_side = "LONG"
    watched_entry = 1918.0
    watched_qty = 33
    initial_qty = 33
    tv_tps = [1925.97, 1940.78, 1955.58]
    regime = 3
    regime_settings = {
        3: {"margin": 0.35, "ratios": [0.30, 0.30, 0.40], "activation": 0.60, "trail_offset": 0.90},
    }
    consumed_tp_levels = []
    best_price = 1918.0
    TP_RETRY_MAX = 3

    def __init__(self):
        self.client = MagicMock()
        self._open = []
        self._place_calls = []

    def _resolve_live_qty(self, q):
        return int(q or self.watched_qty)

    def _safe_qty(self, q):
        return int(float(q or 0))

    def _save_state(self):
        pass

    def _sync_consumed_tp_levels(self, *a, **k):
        pass

    def _cancel_tp_orders_for_consumed_levels(self):
        return 0

    def _collect_tp_limit_orders(self):
        return [
            {
                "orderId": o["orderId"],
                "price": float(o["price"]),
                "qty": int(o["qty"]),
            }
            for o in self._open
        ]

    def _expected_tp_levels(self, live_qty, curr_px=None):
        return [
            {"level": 1, "qty": 10, "price": 1925.97},
            {"level": 2, "qty": 10, "price": 1940.78},
        ]

    def _expected_tp_count(self, tp_pxs=None):
        return 2

    def _consumed_tp_level_set(self):
        return set(self.consumed_tp_levels or [])

    def _has_duplicate_tp_orders(self, tolerance=None):
        return DeepcoinPositionSupervisor._has_duplicate_tp_orders(self, tolerance)

    def _purge_duplicate_tp_orders(self, live_qty):
        return DeepcoinPositionSupervisor._purge_duplicate_tp_orders(self, live_qty)

    def _place_limit_with_retry(self, close_side, pos_side, q, px, label=""):
        self._place_calls.append({"q": q, "px": px, "label": label})
        oid = 9000 + len(self._place_calls)
        self._open.append({"orderId": oid, "price": px, "qty": q})
        return {"ok": True, "order_id": oid}

    def _mark_tp_placed(self, level, order_id=None):
        pass

    def _alert(self, *a, **k):
        pass


def test_deepcoin_rebuild_skips_when_matching_limits_already_on_book():
    h = _DcHost()
    h._open = [
        {"orderId": 101, "price": 1925.97, "qty": 10},
        {"orderId": 102, "price": 1940.78, "qty": 10},
    ]
    h.client.get_current_price.return_value = 1910.0
    h.client.cancel_order = MagicMock()

    placed = DeepcoinPositionSupervisor._rebuild_defenses(h, 33, 1918.0)
    assert placed == 0
    assert h._place_calls == []
    assert len(h._open) == 2


def test_deepcoin_rebuild_purges_duplicates_before_place():
    h = _DcHost()
    h._open = [
        {"orderId": 201, "price": 1925.97, "qty": 10},
        {"orderId": 202, "price": 1925.97, "qty": 10},
        {"orderId": 203, "price": 1940.78, "qty": 10},
        {"orderId": 204, "price": 1940.78, "qty": 10},
    ]
    h.client.get_current_price.return_value = 1910.0

    def _cancel(symbol, ord_id=None, **kw):
        oid = ord_id or kw.get("ord_id")
        h._open = [o for o in h._open if int(o["orderId"]) != int(oid)]

    h.client.cancel_order.side_effect = _cancel

    placed = DeepcoinPositionSupervisor._rebuild_defenses(h, 33, 1918.0)
    assert placed == 0
    assert h._place_calls == []
    prices = [float(o["price"]) for o in h._open]
    assert prices.count(1925.97) == 1
    assert prices.count(1940.78) == 1
    assert all(tp_price_matches(p, 1925.97) or tp_price_matches(p, 1940.78) for p in prices)
