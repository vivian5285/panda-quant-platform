"""TP timeout must not thrash: healthy resting TPs stay; consumed not cleared when book empty."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.position_supervisor import PositionSupervisor


@pytest.fixture
def sup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock(exchange_id="binance")
    client.get_current_price.return_value = 1910.0
    client.get_open_orders.return_value = []
    s = PositionSupervisor(user_id=6, client=client, initial_principal=1000.0)
    s.symbol = "ETHUSDT"
    s.current_side = "LONG"
    s.watched_entry = 1918.0
    s.watched_qty = 0.033
    s.initial_qty = 0.033
    s.tv_tps = [1925.97, 1940.78, 1955.58]
    s.regime = 3
    s.best_price = 1919.0
    s.consumed_tp_levels = [1, 2]
    s._save_state = MagicMock()
    return s


def test_sync_consumed_keeps_timeout_marks_when_book_empty_and_full_qty(sup):
    """After timeout cancel, live==anchor + empty book must NOT wipe consumed."""
    out = PositionSupervisor._sync_consumed_tp_levels(sup, 0.033, 1910.0)
    assert 1 in (sup.consumed_tp_levels or [])
    assert 2 in (sup.consumed_tp_levels or [])
    assert out  # merged non-empty


def test_sync_consumed_clears_only_when_tp_still_on_book(sup):
    sup.client.get_open_orders.return_value = [
        {"orderId": 1, "type": "LIMIT", "side": "SELL", "price": "1925.97",
         "origQty": "0.016", "reduceOnly": True},
    ]
    # Need _open_tp_prices_on_book / collect to see it — use mixin path via real methods
    if hasattr(sup, "_collect_tp_limit_orders"):
        # Force open prices path
        pass
    # Monkeypatch open prices helper
    sup._open_tp_prices_on_book = lambda: [1925.97]
    PositionSupervisor._sync_consumed_tp_levels(sup, 0.033, 1910.0)
    assert list(sup.consumed_tp_levels or []) == []


def test_timeout_refreshes_stamp_for_healthy_resting_tp(sup):
    import time
    sup.consumed_tp_levels = []
    old = time.time() - 400  # older than 300s
    sup._tp_placed_at = {"1": old, "2": old}
    cancelled = []
    sup._cancel_tp_orders_at_levels = lambda levels: cancelled.extend(levels) or 0
    PositionSupervisor._process_radar_trailing(sup, 0.033, 1910.0)
    assert cancelled == []  # must not cancel healthy TPs below mark
    assert float(sup._tp_placed_at["1"]) > old  # stamp refreshed
