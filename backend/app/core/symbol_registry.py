"""Dual-symbol registry: ETHUSDT + XAUUSDT across Binance / OKX / Gate / Deepcoin."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# Canonical IDs used in DB, webhooks, UI, supervisor keys
CANONICAL_ETH = "ETHUSDT"
CANONICAL_XAU = "XAUUSDT"
SUPPORTED_CANONICAL = frozenset({CANONICAL_ETH, CANONICAL_XAU})
DEFAULT_CANONICAL = CANONICAL_ETH

# Per-exchange native instrument IDs
EXCHANGE_SYMBOLS: dict[str, dict[str, str]] = {
    "binance": {
        CANONICAL_ETH: "ETHUSDT",
        CANONICAL_XAU: "XAUUSDT",
    },
    "okx": {
        CANONICAL_ETH: "ETH-USDT-SWAP",
        CANONICAL_XAU: "XAU-USDT-SWAP",
    },
    "gate": {
        CANONICAL_ETH: "ETH_USDT",
        CANONICAL_XAU: "XAU_USDT",
    },
    "deepcoin": {
        CANONICAL_ETH: "ETH-USDT-SWAP",
        CANONICAL_XAU: "XAU-USDT-SWAP",
    },
}

# Price tick / qty step per canonical symbol (USDT-M style)
SYMBOL_PRECISION: dict[str, dict[str, Any]] = {
    CANONICAL_ETH: {
        "price_tick": Decimal("0.01"),
        "qty_step": Decimal("0.001"),
        "price_decimals": 2,
        "qty_decimals": 3,
        "min_qty": 0.001,
        "qty_unit": "ETH",
        "label": "ETH 永续",
        "dingtalk_unit": "ETH",
    },
    CANONICAL_XAU: {
        "price_tick": Decimal("0.01"),
        "qty_step": Decimal("0.01"),
        "price_decimals": 2,
        "qty_decimals": 2,
        "min_qty": 0.01,
        "qty_unit": "XAU",
        "label": "XAU 永续",
        "dingtalk_unit": "盎司",
    },
}

# Aliases TV / Pine / exchanges may send
_SYMBOL_ALIASES: dict[str, str] = {
    "ETHUSDT": CANONICAL_ETH,
    "ETH-USDT": CANONICAL_ETH,
    "ETH-USDT-SWAP": CANONICAL_ETH,
    "ETH_USDT": CANONICAL_ETH,
    "ETHUSD": CANONICAL_ETH,
    "ETH": CANONICAL_ETH,
    "XAUUSDT": CANONICAL_XAU,
    "XAUUSD": CANONICAL_XAU,
    "XAU-USDT": CANONICAL_XAU,
    "XAU-USDT-SWAP": CANONICAL_XAU,
    "XAU_USDT": CANONICAL_XAU,
    "XAU": CANONICAL_XAU,
    "GOLD": CANONICAL_XAU,
    "PAXGUSDT": CANONICAL_XAU,
}


def normalize_canonical_symbol(raw: str | None, *, default: str | None = DEFAULT_CANONICAL) -> str | None:
    """Map any TV/exchange ticker to canonical ETHUSDT / XAUUSDT."""
    if raw is None or str(raw).strip() == "":
        return default
    key = str(raw).strip().upper().replace(" ", "")
    if key in SUPPORTED_CANONICAL:
        return key
    mapped = _SYMBOL_ALIASES.get(key)
    if mapped:
        return mapped
    # Loose contains
    if "XAU" in key or "GOLD" in key or "PAXG" in key:
        return CANONICAL_XAU
    if "ETH" in key:
        return CANONICAL_ETH
    return default


def exchange_native_symbol(exchange: str | None, canonical: str | None) -> str:
    ex = (exchange or "binance").strip().lower()
    if ex == "gateio":
        ex = "gate"
    can = normalize_canonical_symbol(canonical) or DEFAULT_CANONICAL
    return EXCHANGE_SYMBOLS.get(ex, EXCHANGE_SYMBOLS["binance"]).get(can, can)


def canonical_from_native(exchange: str | None, native: str | None) -> str:
    return normalize_canonical_symbol(native) or DEFAULT_CANONICAL


def symbol_meta(canonical: str | None) -> dict[str, Any]:
    can = normalize_canonical_symbol(canonical) or DEFAULT_CANONICAL
    return dict(SYMBOL_PRECISION.get(can, SYMBOL_PRECISION[DEFAULT_CANONICAL]))


def qty_unit_for_symbol(canonical: str | None, exchange: str | None = None) -> str:
    can = normalize_canonical_symbol(canonical) or DEFAULT_CANONICAL
    if (exchange or "").lower() == "deepcoin":
        return "张"
    return str(symbol_meta(can).get("dingtalk_unit") or symbol_meta(can).get("qty_unit") or "ETH")


def label_for_symbol(canonical: str | None) -> str:
    return str(symbol_meta(canonical).get("label") or canonical or "ETH")


def extract_payload_symbol(payload: dict | None) -> str:
    """Pull symbol from TV webhook (symbol / ticker / pair). Default ETH for legacy alerts."""
    data = dict(payload or {})
    for key in ("symbol", "ticker", "pair", "market", "instId", "contract"):
        raw = data.get(key)
        if raw is not None and str(raw).strip():
            return normalize_canonical_symbol(str(raw)) or DEFAULT_CANONICAL
    return DEFAULT_CANONICAL


def enabled_trading_symbols() -> list[str]:
    """Ordered list of symbols the VPS runs for each user."""
    from app.config import get_settings

    settings = get_settings()
    raw = str(getattr(settings, "TRADING_SYMBOLS", "ETHUSDT,XAUUSDT") or "ETHUSDT,XAUUSDT")
    out: list[str] = []
    for part in raw.split(","):
        can = normalize_canonical_symbol(part.strip(), default=None)
        if can and can not in out:
            out.append(can)
    return out or [DEFAULT_CANONICAL]


def supervisor_state_key(exchange: str | None, user_id: int, canonical: str | None) -> str:
    ex = (exchange or "binance").strip().lower()
    can = (normalize_canonical_symbol(canonical) or DEFAULT_CANONICAL).lower()
    return f"{ex}_{user_id}_{can}"
