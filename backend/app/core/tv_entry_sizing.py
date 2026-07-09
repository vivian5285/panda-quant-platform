"""v6.9.85 TV proportional sizing — risk_pct × leverage × qty_ratio on VPS principal."""

from __future__ import annotations

from typing import Any

from app.core.position_sizing import (
    compute_deepcoin_contracts,
    compute_eth_qty,
    resolve_principal_sizing_base,
)

ENTRY_TYPES = frozenset({"OPEN", "PYRAMID", "PROFIT_ADD"})
ENTRY_TYPES_ADD = frozenset({"PYRAMID", "PROFIT_ADD"})


def _parse_float(raw, default: float | None = None) -> float | None:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def normalize_risk_pct(risk_pct: float) -> float:
    """TV sends percent points (e.g. 1.35 = 1.35% of principal)."""
    v = float(risk_pct or 0)
    if v <= 0:
        return 0.0
    return v / 100.0


def parse_tv_entry_fields(payload: dict | None) -> dict[str, Any]:
    data = dict(payload or {})
    entry_type = str(data.get("entry_type") or "OPEN").upper().strip()
    if entry_type not in ENTRY_TYPES:
        entry_type = "OPEN"
    risk_pct = _parse_float(data.get("risk_pct"))
    qty_ratio = _parse_float(data.get("qty_ratio"), default=1.0) or 1.0
    tv_leverage = _parse_float(data.get("leverage"))
    return {
        "entry_type": entry_type,
        "risk_pct": risk_pct,
        "qty_ratio": max(float(qty_ratio), 0.01),
        "tv_leverage": tv_leverage,
        "uses_tv_sizing": bool(risk_pct and risk_pct > 0),
    }


def compute_tv_notional_usd(
    sizing_base: float,
    *,
    risk_pct: float,
    leverage: float,
    qty_ratio: float = 1.0,
) -> tuple[float, float, float]:
    """
    下单名义价值 = 本金 × risk_pct × leverage × qty_ratio
    (risk_pct 为 TV 百分比点数，内部 normalize 为小数)
    """
    risk_frac = normalize_risk_pct(risk_pct)
    qr = max(float(qty_ratio or 1.0), 0.01)
    lev = max(float(leverage or 1), 1.0)
    base = max(float(sizing_base or 0), 0.0)
    margin_usd = base * risk_frac * qr
    notional_usd = margin_usd * lev
    max_notional = base * lev
    if max_notional > 0:
        notional_usd = min(notional_usd, max_notional)
    return round(margin_usd, 4), round(notional_usd, 4), round(max_notional, 4)


def compute_tv_eth_qty(
    *,
    live_balance: float,
    initial_principal: float,
    risk_pct: float,
    leverage: int,
    qty_ratio: float,
    price: float,
    round_fn,
) -> tuple[float, dict]:
    sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)
    margin_usd, notional_usd, max_notional = compute_tv_notional_usd(
        sizing_base,
        risk_pct=risk_pct,
        leverage=leverage,
        qty_ratio=qty_ratio,
    )
    qty = round_fn(notional_usd / price) if price > 0 else 0.0
    return qty, {
        "sizing_mode": "tv_v6985_proportional",
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "risk_pct": round(float(risk_pct), 4),
        "risk_frac": round(normalize_risk_pct(risk_pct), 6),
        "qty_ratio": round(float(qty_ratio), 4),
        "margin_usd": margin_usd,
        "notional_usd": notional_usd,
        "max_notional_usd": max_notional,
        "equity_balance": round(live_balance, 2),
        "initial_principal": round(initial_principal, 2),
        "leverage": int(leverage),
        "price": round(price, 2),
    }


def compute_tv_deepcoin_contracts(
    *,
    live_balance: float,
    initial_principal: float,
    risk_pct: float,
    leverage: int,
    qty_ratio: float,
    price: float,
    face_value: float,
) -> tuple[int, dict]:
    sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)
    margin_usd, notional_usd, max_notional = compute_tv_notional_usd(
        sizing_base,
        risk_pct=risk_pct,
        leverage=leverage,
        qty_ratio=qty_ratio,
    )
    denom = price * face_value
    qty = max(int(notional_usd / denom), 1) if denom > 0 else 1
    return qty, {
        "sizing_mode": "tv_v6985_proportional",
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "risk_pct": round(float(risk_pct), 4),
        "risk_frac": round(normalize_risk_pct(risk_pct), 6),
        "qty_ratio": round(float(qty_ratio), 4),
        "margin_usd": margin_usd,
        "notional_usd": notional_usd,
        "max_notional_usd": max_notional,
        "equity_balance": round(live_balance, 2),
        "initial_principal": round(initial_principal, 2),
        "leverage": int(leverage),
        "price": round(price, 2),
        "face_value": face_value,
    }


def resolve_entry_order_qty_eth(
    *,
    live_balance: float,
    initial_principal: float,
    price: float,
    regime_margin_pct: float,
    exchange_leverage: int,
    round_fn,
    tv_fields: dict | None,
) -> tuple[float, dict]:
    tv = dict(tv_fields or {})
    if tv.get("uses_tv_sizing") and tv.get("risk_pct"):
        lev = int(exchange_leverage or 1)
        return compute_tv_eth_qty(
            live_balance=live_balance,
            initial_principal=initial_principal,
            risk_pct=float(tv["risk_pct"]),
            leverage=lev,
            qty_ratio=float(tv.get("qty_ratio") or 1.0),
            price=price,
            round_fn=round_fn,
        )
    return compute_eth_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        margin_pct=regime_margin_pct,
        leverage=exchange_leverage,
        price=price,
        round_fn=round_fn,
    )


def resolve_entry_order_qty_deepcoin(
    *,
    live_balance: float,
    initial_principal: float,
    price: float,
    regime_margin_pct: float,
    exchange_leverage: int,
    face_value: float,
    tv_fields: dict | None,
) -> tuple[int, dict]:
    tv = dict(tv_fields or {})
    if tv.get("uses_tv_sizing") and tv.get("risk_pct"):
        lev = int(exchange_leverage or 1)
        return compute_tv_deepcoin_contracts(
            live_balance=live_balance,
            initial_principal=initial_principal,
            risk_pct=float(tv["risk_pct"]),
            leverage=lev,
            qty_ratio=float(tv.get("qty_ratio") or 1.0),
            price=price,
            face_value=face_value,
        )
    return compute_deepcoin_contracts(
        live_balance=live_balance,
        initial_principal=initial_principal,
        margin_pct=regime_margin_pct,
        leverage=exchange_leverage,
        price=price,
        face_value=face_value,
    )
