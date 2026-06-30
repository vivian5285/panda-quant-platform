"""ETHUSDT price/qty precision for Binance futures orders."""
from app.core.symbol_precision import (
    format_price,
    format_quantity,
    normalize_entry_payload,
    normalize_tv_targets,
    round_price,
    round_quantity,
)


def test_format_price_two_decimals():
    assert format_price(3500.123456) == "3500.12"
    assert format_price(3500.999) == "3501.00"
    assert format_price("3688.4567") == "3688.46"


def test_format_price_avoids_float_artifacts():
    # Python round(2.675, 2) != 2.68; Decimal quantize must be stable
    assert format_price(2.675) == "2.68"
    assert format_price(3500.005) == "3500.01"


def test_format_quantity_three_decimals():
    assert format_quantity(1.23456) == "1.234"
    assert format_quantity(0.0009) == "0.000"


def test_normalize_tv_targets():
    assert normalize_tv_targets([3600.123, 3700.999, 3800.001]) == [3600.12, 3701.0, 3800.0]


def test_normalize_entry_payload():
    raw = {
        "action": "LONG",
        "price": 3500.789,
        "tv_tp1": 3600.111,
        "tv_tp2": 3700.555,
        "tv_tp3": 3800.999,
        "regime": 1,
    }
    out = normalize_entry_payload(raw)
    assert out["price"] == 3500.79
    assert out["tv_tp1"] == 3600.11
    assert out["tv_tp2"] == 3700.56
    assert out["tv_tp3"] == 3801.0


def test_round_price_and_quantity():
    assert round_price(3500.126) == 3500.13
    assert round_quantity(1.2349) == 1.234
