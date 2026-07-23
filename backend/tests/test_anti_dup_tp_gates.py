"""Anti-duplicate TP / close-side guards (2026-07-23 ghost LIMIT storm)."""

from app.core.binance_smart_defense import BinanceSmartDefenseMixin


class _T(BinanceSmartDefenseMixin):
    def __init__(self):
        self.current_side = None
        self.watched_qty = 0.0
        self.symbol = "ETHUSDT"
        self._orders = []

    def _get_active_position(self):
        return self._pos

    def _collect_tp_limit_orders(self):
        return list(self._orders)

    def _tp_price_tol(self):
        return 0.5

    def _def_log(self, *a, **k):
        pass

    def _resolve_live_qty(self, fallback_qty: float) -> float:
        if self._pos and self._pos.get("size", 0) > 0:
            return float(self._pos["size"])
        return float(fallback_qty or 0)

    def _purge_duplicate_tp_orders(self, live_qty):
        return 0


def test_tp_close_side_from_long_position():
    t = _T()
    t._pos = {"size": 0.01, "side": "LONG"}
    assert t._tp_close_side_label() == "SHORT"


def test_tp_close_side_unknown_refuses_default_long():
    t = _T()
    t._pos = None
    t.current_side = None
    assert t._tp_close_side_label() is None


def test_refuse_when_book_saturated():
    t = _T()
    t._pos = {"size": 0.01, "side": "LONG"}
    t._orders = [
        {"price": 1.0, "qty": 0.003, "orderId": 1},
        {"price": 2.0, "qty": 0.003, "orderId": 2},
        {"price": 3.0, "qty": 0.003, "orderId": 3},
    ]
    assert t._refuse_tp_place_if_saturated(expected=2) is True


def test_exists_near_idempotent():
    t = _T()
    t._orders = [{"price": 1900.0, "qty": 0.005, "orderId": 9}]
    assert t._tp_limit_exists_near(1900.0) is True
    assert t._tp_limit_exists_near(1910.0) is False
