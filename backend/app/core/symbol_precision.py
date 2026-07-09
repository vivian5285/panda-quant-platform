"""Binance USDT-M ETHUSDT perpetual tick / step formatting."""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

# ETHUSDT USDT-M: price tick 0.01, quantity step 0.001 (Binance futures)
PRICE_TICK = Decimal("0.01")
QTY_STEP = Decimal("0.001")
PRICE_DECIMALS = 2
QTY_DECIMALS = 3


def round_price(value) -> float:
    if value is None:
        return 0.0
    d = Decimal(str(value)).quantize(PRICE_TICK, rounding=ROUND_HALF_UP)
    return float(d)


def format_price(value) -> str:
    """Exchange-safe price string (max 2 decimal places)."""
    d = Decimal(str(value or 0)).quantize(PRICE_TICK, rounding=ROUND_HALF_UP)
    return format(d, "f")


def round_quantity(value) -> float:
    if value is None:
        return 0.0
    d = Decimal(str(value)).quantize(QTY_STEP, rounding=ROUND_DOWN)
    return float(d)


def format_quantity(value) -> str:
    """Exchange-safe quantity string (max 3 decimal places)."""
    d = Decimal(str(value or 0)).quantize(QTY_STEP, rounding=ROUND_DOWN)
    return format(d, "f")


def normalize_tv_targets(values: list) -> list[float]:
    out: list[float] = []
    for v in (values or [])[:3]:
        try:
            p = float(v or 0)
            out.append(round_price(p) if p > 0 else 0.0)
        except (TypeError, ValueError):
            out.append(0.0)
    while len(out) < 3:
        out.append(0.0)
    return out


def normalize_entry_payload(data: dict) -> dict:
    """Round TV price / TP fields before dispatch (in-place copy)."""
    out = dict(data)
    if out.get("price") is not None:
        out["price"] = round_price(out["price"])
    for key in ("tv_tp1", "tv_tp2", "tv_tp3"):
        if out.get(key) is not None:
            p = float(out[key] or 0)
            out[key] = round_price(p) if p > 0 else 0.0
    if out.get("tv_sl") is not None:
        out["tv_sl"] = round_price(out["tv_sl"])
    return out
