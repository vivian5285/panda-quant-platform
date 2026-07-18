"""Binance conditional STOP orders use algo book after 2025-12 migration."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.binance_client import BinanceClient


@pytest.fixture
def client():
    with patch("app.core.binance_client.Client") as mock_cls:
        inner = MagicMock()
        mock_cls.return_value = inner
        bc = BinanceClient("k", "s", user_id=6)
        bc.client = inner
        yield bc


def test_place_stop_limit_uses_algo_stop(client):
    """Hard SL must use algo STOP (限价条件单), not classic book / STOP_MARKET close-all."""
    client.client._request_futures_api.return_value = {
        "algoId": 9010,
        "orderType": "STOP",
        "triggerPrice": "1891.82",
        "price": "1894.66",
        "quantity": "0.076",
        "side": "BUY",
        "reduceOnly": True,
    }

    res = client.place_stop_limit_order(
        "BUY", 1891.82, 1894.66, "ETHUSDT", quantity=0.076, reduce_only=True,
    )

    assert res is not None
    assert res.get("algoId") == 9010
    args, kwargs = client.client._request_futures_api.call_args
    assert args[0] == "post" and args[1] == "algoOrder"
    data = kwargs.get("data") or {}
    assert data["algoType"] == "CONDITIONAL"
    assert data["type"] == "STOP"
    assert "closePosition" not in data
    assert float(data["quantity"]) == pytest.approx(0.076)
    assert float(data["triggerPrice"]) == pytest.approx(1891.82)
    assert float(data["price"]) == pytest.approx(1894.66)
    client.client.futures_create_order.assert_not_called()


def test_place_stop_market_uses_algo_close_position(client):
    client.client._request_futures_api.return_value = {
        "algoId": 9001,
        "orderType": "STOP_MARKET",
        "triggerPrice": "1796.43",
        "closePosition": True,
        "side": "SELL",
    }

    res = client.place_stop_market_order("SHORT", 1796.43, "ETHUSDT", quantity=None)

    assert res is not None
    assert res.get("algoId") == 9001
    client.client._request_futures_api.assert_called_once()
    args, kwargs = client.client._request_futures_api.call_args
    assert args[0] == "post" and args[1] == "algoOrder"
    data = kwargs.get("data") or {}
    assert data["algoType"] == "CONDITIONAL"
    assert data["type"] == "STOP_MARKET"
    assert data["closePosition"] == "true"
    assert "quantity" not in data
    client.client.futures_create_order.assert_not_called()


def test_get_open_orders_merges_algo_book(client):
    client.client.futures_get_open_orders.return_value = [
        {"orderId": 1, "type": "LIMIT", "price": "1830.00", "origQty": "0.020"},
    ]
    client.client._request_futures_api.return_value = [
        {
            "algoId": 9001,
            "orderType": "STOP_MARKET",
            "triggerPrice": "1796.43",
            "closePosition": True,
            "algoStatus": "NEW",
            "side": "SELL",
        }
    ]

    orders = client.get_open_orders("ETHUSDT")

    assert len(orders) == 2
    stop = next(o for o in orders if o.get("type") == "STOP_MARKET")
    assert float(stop["triggerPrice"]) == pytest.approx(1796.43)
    assert stop.get("isAlgoOrder") is True


def test_get_algo_order_direct_lookup(client):
    client.client._request_futures_api.return_value = {
        "algoId": 9003,
        "orderType": "STOP_MARKET",
        "triggerPrice": "1904.46",
        "closePosition": True,
        "algoStatus": "NEW",
        "side": "BUY",
    }
    row = client.get_algo_order("ETHUSDT", 9003)
    assert row is not None
    assert row["algoId"] == 9003
    assert float(row["triggerPrice"]) == pytest.approx(1904.46)
    assert row["closePosition"] == "true"


def test_get_open_algo_orders_parses_orders_wrapper(client):
    client.client.futures_get_open_orders.return_value = []
    client.client._request_futures_api.return_value = {
        "orders": [
            {
                "algoId": 9004,
                "orderType": "STOP_MARKET",
                "triggerPrice": "1904.46",
                "closePosition": True,
                "algoStatus": "NEW",
                "side": "BUY",
            }
        ]
    }
    orders = client.get_open_algo_orders("ETHUSDT")
    assert len(orders) == 1
    assert orders[0]["algoId"] == 9004


def test_cancel_order_falls_back_to_algo(client):
    client.client.futures_cancel_order.side_effect = Exception("not found")
    client.client._request_futures_api.return_value = {"algoId": 9001}

    ok = client.cancel_order("ETHUSDT", 9001)

    assert ok is True
    client.client._request_futures_api.assert_called_once()
    assert client.client._request_futures_api.call_args[0][:2] == ("delete", "algoOrder")
