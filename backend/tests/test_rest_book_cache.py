"""Shared REST book cache — dual-symbol merge tests."""

from app.core.ip_rest_cooldown import note_rate_limit, reset_for_tests as reset_cool
from app.core.rest_book_cache import (
    get_cached_open_orders,
    get_cached_position,
    invalidate,
    reset_for_tests,
)


def test_position_cache_one_fetch_serves_two_symbols():
    reset_for_tests()
    reset_cool()
    calls = {"n": 0}

    def fetch_all():
        calls["n"] += 1
        return [
            {"symbol": "ETHUSDT", "positionAmt": "0.031", "entryPrice": "1900"},
            {"symbol": "XAUUSDT", "positionAmt": "0.014", "entryPrice": "4100"},
        ]

    eth = get_cached_position(
        exchange="binance", user_id=6, symbol="ETHUSDT", fetch_all=fetch_all,
    )
    xau = get_cached_position(
        exchange="binance", user_id=6, symbol="XAUUSDT", fetch_all=fetch_all,
    )
    assert eth["positionAmt"] == "0.031"
    assert xau["positionAmt"] == "0.014"
    assert calls["n"] == 1  # second symbol hit cache


def test_orders_cache_and_invalidate():
    reset_for_tests()
    reset_cool()
    calls = {"n": 0}

    def fetch_all():
        calls["n"] += 1
        return [
            {"symbol": "ETHUSDT", "orderId": 1, "type": "LIMIT"},
            {"symbol": "XAUUSDT", "orderId": 2, "type": "LIMIT"},
        ]

    eth = get_cached_open_orders(
        exchange="binance", user_id=6, symbol="ETHUSDT", fetch_all=fetch_all,
    )
    xau = get_cached_open_orders(
        exchange="binance", user_id=6, symbol="XAUUSDT", fetch_all=fetch_all,
    )
    assert len(eth) == 1 and eth[0]["orderId"] == 1
    assert len(xau) == 1 and xau[0]["orderId"] == 2
    assert calls["n"] == 1

    invalidate("binance", 6, reason="test")
    get_cached_open_orders(
        exchange="binance", user_id=6, symbol="ETHUSDT", fetch_all=fetch_all,
    )
    assert calls["n"] == 2


def test_cool_down_serves_stale_without_fetch():
    reset_for_tests()
    reset_cool()
    calls = {"n": 0}

    def fetch_all():
        calls["n"] += 1
        return [{"symbol": "ETHUSDT", "positionAmt": "0.031", "entryPrice": "1896"}]

    get_cached_position(
        exchange="binance", user_id=6, symbol="ETHUSDT", fetch_all=fetch_all,
    )
    assert calls["n"] == 1

    note_rate_limit(exchange="binance", user_id=6, cool_sec=90.0)
    invalidate("binance", 6, reason="place")  # soft expire only
    eth = get_cached_position(
        exchange="binance", user_id=6, symbol="ETHUSDT", fetch_all=fetch_all,
    )
    assert eth["positionAmt"] == "0.031"
    assert calls["n"] == 1  # no REST under cool-down
