"""Book-unreadable + same-price TP storm fuse (2026-07-23)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.binance_smart_defense import BinanceSmartDefenseMixin
from app.core.adverse_radar_guard import AdverseRadarMixin


class _T(BinanceSmartDefenseMixin):
    def __init__(self):
        self.user_id = 6
        self.current_side = "LONG"
        self.watched_qty = 0.01
        self.symbol = "ETHUSDT"
        self.tv_tps = [1900.0, 1910.0, 0.0]
        self.regime = 3
        self.regime_settings = {3: {"ratios": [0.3, 0.3, 0.4]}}
        self._orders = []
        self.client = MagicMock()
        self.logs = []

    def _get_active_position(self):
        return {"size": 0.01, "side": "LONG"}

    def _collect_tp_limit_orders(self):
        if getattr(self, "_book_boom", False):
            raise RuntimeError("book_unreadable")
        return list(self._orders)

    def _tp_price_tol(self):
        return 0.5

    def _def_log(self, msg, level=None):
        self.logs.append(str(msg))

    def _resolve_live_qty(self, fallback_qty: float) -> float:
        return float(fallback_qty or 0)

    def _expected_tp_levels(self, live_qty, curr_px=None):
        return [
            {"level": 1, "qty": 0.003, "price": 1900.0},
            {"level": 2, "qty": 0.003, "price": 1910.0},
        ]


def test_exists_near_unreadable_is_none():
    t = _T()
    t._book_boom = True
    assert t._tp_limit_exists_near(1900.0) is None


def test_refuse_when_unreadable():
    t = _T()
    t._book_boom = True
    assert t._refuse_tp_place_if_saturated(expected=2) is True


def test_storm_fuse_at_6():
    t = _T()
    t._orders = [
        {"price": 1900.0, "qty": 0.001, "orderId": i} for i in range(6)
    ]
    assert t._refuse_tp_place_if_saturated(expected=2) is True


def test_soft_dedupe_keeps_one_per_price():
    t = _T()
    t._orders = [
        {"price": 1900.0, "qty": 0.003, "orderId": 1},
        {"price": 1900.0, "qty": 0.003, "orderId": 2},
        {"price": 1900.0, "qty": 0.001, "orderId": 3},
        {"price": 1910.0, "qty": 0.003, "orderId": 4},
    ]
    cancelled = t._soft_dedupe_tp_same_price(0.01)
    assert cancelled == 2
    assert t.client.cancel_order.call_count == 2


def test_soft_dedupe_unreadable_no_cancel_all():
    t = _T()
    t._book_boom = True
    assert t._soft_dedupe_tp_same_price(0.01) == -1
    t.client.cancel_all_open_orders.assert_not_called()
    t.client.cancel_order.assert_not_called()


def test_cancel_all_tp_unreadable_returns_minus_one():
    t = _T()
    t.client.get_open_orders.side_effect = RuntimeError("banned")
    assert t._cancel_all_tp_limit_orders() == -1
    t.client.cancel_all_open_orders.assert_not_called()


def test_has_stop_sl_near_unreadable_is_none():
    t = _T()
    t.client.get_open_orders.side_effect = RuntimeError("timeout")
    assert t._has_stop_sl_near(1876.0) is None


class _HardHost(AdverseRadarMixin):
    def __init__(self):
        self.user_id = 6
        self.symbol = "ETHUSDT"
        self.exchange_id = "binance"
        self.current_side = "LONG"
        self.watched_entry = 1900.0
        self.tv_sl = 1876.0
        self._frozen_hard_stop_px = 1876.0
        self._defense_order_ids = {"hard": 999}
        self.client = MagicMock()

    def _frozen_hard_px(self):
        return 1876.0

    def _exchange_hang_stop_px(self, px):
        return float(px)

    def _hard_stop_label(self):
        return "HARD"

    def _resolve_adverse_live_qty(self, q):
        return float(q)

    def _has_stop_sl_near(self, sl_price, tolerance=2.0):
        return None

    def _count_live_stop_orders(self):
        return -1

    def _place_adverse_stop_slice(self, hang, qty):
        raise AssertionError("must not place when book unread")


def test_sync_hard_refuses_claim_present_when_unread():
    h = _HardHost()
    out = h._sync_hard_stop_only(0.01, force_replace=False)
    assert out.get("armed") is False
    assert out.get("reason") == "book_unknown"
    assert "refuse_claim" in str(out.get("skipped") or "")
