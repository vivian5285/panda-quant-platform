"""v6.9.85 TV proportional sizing — risk_pct × leverage × qty_ratio on VPS principal."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.core.position_sizing import (
    compute_deepcoin_contracts,
    compute_eth_qty,
    resolve_principal_sizing_base,
)
from app.core.regime_utils import clamp_regime

settings = get_settings()

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


def regime_vps_coefficient(regime: int) -> float:
    """VPS 档位系数 — TV regime → 下单风险放大/保守系数."""
    r = clamp_regime(int(regime or 3))
    return {
        1: float(settings.REGIME_VPS_COEFF_1),
        2: float(settings.REGIME_VPS_COEFF_2),
        3: float(settings.REGIME_VPS_COEFF_3),
        4: float(settings.REGIME_VPS_COEFF_4),
    }.get(r, 1.0)


def apply_vps_regime_risk(
    tv_risk_pct: float,
    regime: int,
    *,
    max_risk_pct_limit: float | None = None,
) -> dict[str, Any]:
    """
    最终风险% = TV risk_pct × VPS档位系数，超过 MAX_RISK_PCT_LIMIT 则截断。
    例：regime4 × 1.25 后 4.875% → clamp 至 4.0%。
    """
    raw = float(tv_risk_pct or 0)
    r = clamp_regime(int(regime or 3))
    coeff = regime_vps_coefficient(r)
    cap = float(max_risk_pct_limit if max_risk_pct_limit is not None else settings.MAX_RISK_PCT_LIMIT)
    scaled = raw * coeff
    effective = min(scaled, cap) if cap > 0 else scaled
    return {
        "regime": r,
        "tv_risk_pct": round(raw, 4),
        "vps_coeff": round(coeff, 4),
        "scaled_risk_pct": round(scaled, 4),
        "effective_risk_pct": round(effective, 4),
        "risk_clamped": bool(cap > 0 and scaled > cap + 1e-9),
        "max_risk_pct_limit": round(cap, 4),
    }


def parse_tv_entry_fields(payload: dict | None) -> dict[str, Any]:
    data = dict(payload or {})
    entry_type = str(data.get("entry_type") or "OPEN").upper().strip()
    if entry_type not in ENTRY_TYPES:
        entry_type = "OPEN"
    risk_pct = _parse_float(data.get("risk_pct"))
    qty_ratio = _parse_float(data.get("qty_ratio"), default=1.0) or 1.0
    tv_leverage = _parse_float(data.get("leverage"))
    regime_raw = data.get("regime")
    try:
        regime = clamp_regime(int(regime_raw)) if regime_raw is not None else None
    except (TypeError, ValueError):
        regime = None
    return {
        "entry_type": entry_type,
        "risk_pct": risk_pct,
        "qty_ratio": max(float(qty_ratio), 0.01),
        "tv_leverage": tv_leverage,
        "regime": regime,
        "uses_tv_sizing": bool(risk_pct and risk_pct > 0),
    }


def compute_tv_notional_usd(
    sizing_base: float,
    *,
    risk_pct: float,
    leverage: float,
    qty_ratio: float = 1.0,
    regime: int = 3,
) -> tuple[float, float, float, dict[str, Any]]:
    """
    下单名义价值 = 本金 × effective_risk_pct × leverage × qty_ratio
    effective_risk_pct = min(TV risk_pct × VPS系数, MAX_RISK_PCT_LIMIT)
    """
    risk_meta = apply_vps_regime_risk(risk_pct, regime)
    effective_pct = float(risk_meta["effective_risk_pct"])
    risk_frac = normalize_risk_pct(effective_pct)
    qr = max(float(qty_ratio or 1.0), 0.01)
    lev = max(float(leverage or 1), 1.0)
    base = max(float(sizing_base or 0), 0.0)
    margin_usd = base * risk_frac * qr
    notional_usd = margin_usd * lev
    max_notional = base * lev
    if max_notional > 0:
        notional_usd = min(notional_usd, max_notional)
    return round(margin_usd, 4), round(notional_usd, 4), round(max_notional, 4), risk_meta


def compute_tv_eth_qty(
    *,
    live_balance: float,
    initial_principal: float,
    risk_pct: float,
    leverage: int,
    qty_ratio: float,
    price: float,
    round_fn,
    regime: int = 3,
) -> tuple[float, dict]:
    sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)
    margin_usd, notional_usd, max_notional, risk_meta = compute_tv_notional_usd(
        sizing_base,
        risk_pct=risk_pct,
        leverage=leverage,
        qty_ratio=qty_ratio,
        regime=regime,
    )
    qty = round_fn(notional_usd / price) if price > 0 else 0.0
    effective_pct = float(risk_meta["effective_risk_pct"])
    return qty, {
        "sizing_mode": "tv_v6985_proportional",
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "risk_pct": round(float(risk_pct), 4),
        "effective_risk_pct": round(effective_pct, 4),
        "risk_frac": round(normalize_risk_pct(effective_pct), 6),
        "vps_coeff": risk_meta["vps_coeff"],
        "scaled_risk_pct": risk_meta["scaled_risk_pct"],
        "risk_clamped": risk_meta["risk_clamped"],
        "max_risk_pct_limit": risk_meta["max_risk_pct_limit"],
        "regime": risk_meta["regime"],
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
    regime: int = 3,
) -> tuple[int, dict]:
    sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)
    margin_usd, notional_usd, max_notional, risk_meta = compute_tv_notional_usd(
        sizing_base,
        risk_pct=risk_pct,
        leverage=leverage,
        qty_ratio=qty_ratio,
        regime=regime,
    )
    denom = price * face_value
    qty = max(int(notional_usd / denom), 1) if denom > 0 else 1
    effective_pct = float(risk_meta["effective_risk_pct"])
    return qty, {
        "sizing_mode": "tv_v6985_proportional",
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "risk_pct": round(float(risk_pct), 4),
        "effective_risk_pct": round(effective_pct, 4),
        "risk_frac": round(normalize_risk_pct(effective_pct), 6),
        "vps_coeff": risk_meta["vps_coeff"],
        "scaled_risk_pct": risk_meta["scaled_risk_pct"],
        "risk_clamped": risk_meta["risk_clamped"],
        "max_risk_pct_limit": risk_meta["max_risk_pct_limit"],
        "regime": risk_meta["regime"],
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
    regime: int = 3,
) -> tuple[float, dict]:
    tv = dict(tv_fields or {})
    if tv.get("uses_tv_sizing") and tv.get("risk_pct"):
        lev = int(exchange_leverage or 1)
        entry_regime = int(tv.get("regime") or regime or 3)
        return compute_tv_eth_qty(
            live_balance=live_balance,
            initial_principal=initial_principal,
            risk_pct=float(tv["risk_pct"]),
            leverage=lev,
            qty_ratio=float(tv.get("qty_ratio") or 1.0),
            price=price,
            round_fn=round_fn,
            regime=entry_regime,
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
    regime: int = 3,
) -> tuple[int, dict]:
    tv = dict(tv_fields or {})
    if tv.get("uses_tv_sizing") and tv.get("risk_pct"):
        lev = int(exchange_leverage or 1)
        entry_regime = int(tv.get("regime") or regime or 3)
        return compute_tv_deepcoin_contracts(
            live_balance=live_balance,
            initial_principal=initial_principal,
            risk_pct=float(tv["risk_pct"]),
            leverage=lev,
            qty_ratio=float(tv.get("qty_ratio") or 1.0),
            price=price,
            face_value=face_value,
            regime=entry_regime,
        )
    return compute_deepcoin_contracts(
        live_balance=live_balance,
        initial_principal=initial_principal,
        margin_pct=regime_margin_pct,
        leverage=exchange_leverage,
        price=price,
        face_value=face_value,
    )
