from app.core.exchange_errors import parse_binance_error, raise_exchange_transient, ExchangeTransientError
from app.core.ip_rest_cooldown import (
    DEFAULT_COOL_SEC,
    GLOBAL_SUFFIX,
    note_rate_limit,
    remaining_sec,
    reset_for_tests,
    snapshot,
)


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
    # Default cool is 180s (v16.4.2); allow clock skew
    assert remaining_sec(exchange="binance", user_id=6) > 150
    assert remaining_sec(exchange="binance", user_id=99) > 150  # IP-wide
    assert remaining_sec(exchange="binance", user_id=GLOBAL_SUFFIX) > 150


def test_note_rate_limit_shared_ip_and_global():
    reset_for_tests()
    note_rate_limit(exchange="binance", user_id=6, cool_sec=30)
    assert remaining_sec(exchange="binance", user_id=6) > 20
    assert remaining_sec(exchange="binance", user_id=99) > 20  # IP-wide key
    assert remaining_sec(exchange="binance", user_id=GLOBAL_SUFFIX) > 20
    snap = snapshot()
    assert any(GLOBAL_SUFFIX in k for k in snap)


def test_default_cool_sec_is_180():
    assert DEFAULT_COOL_SEC == 180.0
