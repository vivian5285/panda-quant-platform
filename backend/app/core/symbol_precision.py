"""Per-symbol tick / step formatting (ETHUSDT + XAUUSDT)."""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from app.core.symbol_registry import (
    CANONICAL_ETH,
    DEFAULT_CANONICAL,
    normalize_canonical_symbol,
    symbol_meta,
)

# Backward-compatible ETHUSDT defaults (imported widely)
PRICE_TICK = Decimal("0.01")
QTY_STEP = Decimal("0.001")
PRICE_DECIMALS = 2
QTY_DECIMALS = 3


def _meta(symbol: str | None = None) -> dict:
    return symbol_meta(normalize_canonical_symbol(symbol) or DEFAULT_CANONICAL)


def price_tick_for(symbol: str | None = None) -> Decimal:
    return Decimal(str(_meta(symbol).get("price_tick") or PRICE_TICK))


def qty_step_for(symbol: str | None = None) -> Decimal:
    return Decimal(str(_meta(symbol).get("qty_step") or QTY_STEP))


def round_price(value, symbol: str | None = None) -> float:
    if value is None:
        return 0.0
    tick = price_tick_for(symbol)
    d = Decimal(str(value)).quantize(tick, rounding=ROUND_HALF_UP)
    return float(d)


def format_price(value, symbol: str | None = None) -> str:
    tick = price_tick_for(symbol)
    d = Decimal(str(value or 0)).quantize(tick, rounding=ROUND_HALF_UP)
    return format(d, "f")


def round_quantity(value, symbol: str | None = None) -> float:
    if value is None:
        return 0.0
    step = qty_step_for(symbol)
    d = Decimal(str(value)).quantize(step, rounding=ROUND_DOWN)
    return float(d)


def format_quantity(value, symbol: str | None = None) -> str:
    step = qty_step_for(symbol)
    d = Decimal(str(value or 0)).quantize(step, rounding=ROUND_DOWN)
    return format(d, "f")


def min_qty_for(symbol: str | None = None) -> float:
    return float(_meta(symbol).get("min_qty") or 0.001)


def normalize_tv_targets(values: list, symbol: str | None = None) -> list[float]:
    out: list[float] = []
    for v in (values or [])[:3]:
        try:
            p = float(v or 0)
            out.append(round_price(p, symbol) if p > 0 else 0.0)
        except (TypeError, ValueError):
            out.append(0.0)
    while len(out) < 3:
        out.append(0.0)
    return out


def merge_tv_targets(*sources: list | None, symbol: str | None = None) -> list[float]:
    merged = [0.0, 0.0, 0.0]
    for src in sources:
        for i, px in enumerate(normalize_tv_targets(list(src or []), symbol)):
            if px > 0:
                merged[i] = px
    return normalize_tv_targets(merged, symbol)


def normalize_entry_payload(data: dict, symbol: str | None = None) -> dict:
    from app.core.symbol_registry import extract_payload_symbol

    out = dict(data)
    can = symbol or extract_payload_symbol(out)
    out["symbol"] = can
    if out.get("price") is not None:
        out["price"] = round_price(out["price"], can)
    for key in ("tv_tp1", "tv_tp2", "tv_tp3"):
        if out.get(key) is not None:
            p = float(out[key] or 0)
            out[key] = round_price(p, can) if p > 0 else 0.0
    if out.get("tv_sl") is not None:
        out["tv_sl"] = round_price(out["tv_sl"], can)
    return out
