"""DeepCoin hedge (dual-side) vs one-way: list/close all posSides before open."""

from unittest.mock import MagicMock

from app.core.position_supervisor_deepcoin import DeepcoinPositionSupervisor


def _host(positions):
    h = DeepcoinPositionSupervisor.__new__(DeepcoinPositionSupervisor)
    h.user_id = 9
    h.exchange_id = "deepcoin"
    h.symbol = "ETH-USDT-SWAP"
    h.current_side = "LONG"
    h.client = MagicMock()
    h._position_query_degraded = False
    h._position_query_error = ""
    h._position_query_ban_until_ms = None
    h._handle_position_query_failure = MagicMock()
    h._clear_position_query_degraded = MagicMock()
    h._safe_qty = lambda x: int(float(x or 0))
    h.client.get_position_info.return_value = {
        "code": "0",
        "data": [
            {
                "pos": str(p["size"]),
                "avgPx": "2000",
                "posSide": p["posSide"],
            }
            for p in positions
        ],
    }
    return h


def test_list_live_positions_returns_both_hedge_sides():
    h = _host([
        {"size": 3, "posSide": "long"},
        {"size": 2, "posSide": "short"},
    ])
    rows = h._list_live_positions()
    assert len(rows) == 2
    sides = {r["posSide"] for r in rows}
    assert sides == {"long", "short"}


def test_get_active_prefers_booked_side_when_dual():
    h = _host([
        {"size": 1, "posSide": "short"},
        {"size": 5, "posSide": "long"},
    ])
    h.current_side = "LONG"
    pos = h._get_active_position()
    assert pos["posSide"] == "long"
    assert pos["size"] == 5


def test_verify_flat_false_when_either_side_live():
    h = _host([{"size": 1, "posSide": "short"}])
    assert h._verify_flat() is False
    h.client.get_position_info.return_value = {"code": "0", "data": []}
    assert h._verify_flat() is True


def test_flat_all_closes_each_side_and_batch(monkeypatch):
    h = _host([
        {"size": 2, "posSide": "long"},
        {"size": 1, "posSide": "short"},
    ])
    h.client.cancel_all_open_orders = MagicMock()
    h.client.batch_close_position = MagicMock()
    h.client.place_market_order = MagicMock()
    calls = {"n": 0}

    def _pos_info(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "code": "0",
                "data": [
                    {"pos": "2", "avgPx": "1", "posSide": "long"},
                    {"pos": "1", "avgPx": "1", "posSide": "short"},
                ],
            }
        return {"code": "0", "data": []}

    h.client.get_position_info.side_effect = _pos_info
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    ok = h._flat_all_position_sides(rounds=2, reason="test")
    assert ok is True
    h.client.batch_close_position.assert_called()
    # reduceOnly both sides on first list
    assert h.client.place_market_order.call_count >= 2
    sides = {c.args[2] for c in h.client.place_market_order.call_args_list}
    assert "long" in sides and "short" in sides
