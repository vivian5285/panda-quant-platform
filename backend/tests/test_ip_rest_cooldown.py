from app.core.exchange_errors import parse_binance_error, raise_exchange_transient, ExchangeTransientError
from app.core.ip_rest_cooldown import note_rate_limit, remaining_sec, reset_for_tests


def test_parse_1003_without_banned_until():
    meta = parse_binance_error("APIError(code=-1003): Too many requests; current limit of IP is 2400")
    assert meta["code"] == -1003


def test_raise_1003_sets_shared_cooldown():
    reset_for_tests()
    try:
        raise_exchange_transient(
            Exception("APIError(code=-1003): Too many requests"),
            exchange="binance",
            op="get_position",
            user_id=6,
        )
    except ExchangeTransientError as e:
        assert e.code == -1003
        assert e.banned_until_ms and e.banned_until_ms > 0
    assert remaining_sec(exchange="binance", user_id=6) > 60


def test_note_rate_limit_shared_ip():
    reset_for_tests()
    note_rate_limit(exchange="binance", user_id=6, cool_sec=30)
    assert remaining_sec(exchange="binance", user_id=6) > 20
    assert remaining_sec(exchange="binance", user_id=99) > 20  # IP-wide key
