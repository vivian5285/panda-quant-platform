"""VPS entry sizing — OPEN: VPS risk formula; ADD: base_qty × ADD_QTY_RATIO (ignore TV)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.core.position_sizing import resolve_principal_sizing_base
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


def regime_scale(regime: int) -> float:
    """档位系数 — 仅首次 OPEN 使用."""
    r = clamp_regime(int(regime or 3))
    return {
        1: float(settings.REGIME_SCALE_1),
        2: float(settings.REGIME_SCALE_2),
        3: float(settings.REGIME_SCALE_3),
        4: float(settings.REGIME_SCALE_4),
    }.get(r, 1.0)


def effective_vps_risk_pct(regime: int) -> tuple[float, dict[str, Any]]:
    """effective = VPS_RISK_PCT × REGIME_SCALE × GLOBAL_SCALE, clamped to MAX_RISK_PCT."""
    r = clamp_regime(int(regime or 3))
    scale = regime_scale(r)
    global_scale = float(settings.GLOBAL_SCALE or 1.0)
    raw = float(settings.VPS_RISK_PCT) * scale * global_scale
    cap = float(settings.MAX_RISK_PCT)
    floor = float(settings.MIN_VPS_RISK_PCT)
    effective = max(min(raw, cap), floor) if cap > 0 else raw
    return effective, {
        "regime": r,
        "vps_risk_pct": round(float(settings.VPS_RISK_PCT), 4),
        "regime_scale": round(scale, 4),
        "global_scale": round(global_scale, 4),
        "scaled_risk_pct": round(raw, 4),
        "effective_risk_pct": round(effective, 4),
        "risk_clamped": bool(cap > 0 and raw > cap + 1e-9),
        "max_risk_pct": round(cap, 4),
    }


def vps_add_qty_ratio() -> float:
    """固定加仓比例 — TV qty_ratio 完全忽略."""
    return max(float(settings.ADD_QTY_RATIO or 0.5), 0.01)


def parse_tv_entry_fields(payload: dict | None) -> dict[str, Any]:
    data = dict(payload or {})
    entry_type = str(data.get("entry_type") or "OPEN").upper().strip()
    if entry_type not in ENTRY_TYPES:
        entry_type = "OPEN"
    return {
        "entry_type": entry_type,
        "regime": _parse_regime(data.get("regime")),
        "uses_vps_sizing": True,
        "tv_qty_ratio_ignored": entry_type in ENTRY_TYPES_ADD,
    }


def _parse_regime(raw) -> int | None:
    try:
        return clamp_regime(int(raw)) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _clamp_qty(qty: float, *, min_qty: float, max_qty: float) -> float:
    if qty <= 0:
        return 0.0
    if max_qty > 0:
        qty = min(qty, max_qty)
    if min_qty > 0:
        qty = max(qty, min_qty)
    return qty


def compute_vps_open_qty(
    *,
    live_balance: float,
    initial_principal: float,
    price: float,
    tv_sl: float,
    regime: int,
    leverage: int,
    round_fn,
    min_qty: float | None = None,
    max_qty: float | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    OPEN（开发清单最终版）:
      保证金 = 本金 × VPS_RISK_PCT% × LEVERAGE × REGIME_SCALE
      头寸价值 = 保证金 × LEVERAGE
      张数 = 头寸价值 / price
    tv_sl 仅用于挂单止损，不参与张数计算。忽略 TV risk_pct / qty_ratio。
    """
    sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)
    eff_pct, risk_meta = effective_vps_risk_pct(regime)
    lev = max(int(leverage or 1), 1)
    price_f = float(price or 0)
    tv_sl_f = float(tv_sl or 0)
    meta: dict[str, Any] = {
        "sizing_mode": "vps_open",
        "entry_type": "OPEN",
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "leverage": lev,
        "price": round(price_f, 2),
        "tv_sl": round(tv_sl_f, 2),
        "equity_balance": round(live_balance, 2),
        "initial_principal": round(initial_principal, 2),
        **risk_meta,
    }
    if price_f <= 0:
        meta["error"] = "invalid_price"
        return 0.0, meta

    margin_usd = sizing_base * (eff_pct / 100.0) * lev
    position_value = margin_usd * lev
    raw_qty = position_value / price_f
    meta["margin_usd"] = round(margin_usd, 4)
    meta["position_value"] = round(position_value, 4)
    meta["order_amount"] = round(position_value, 4)
    if tv_sl_f > 0:
        meta["sl_distance"] = round(abs(price_f - tv_sl_f), 4)

    mn = float(min_qty if min_qty is not None else settings.MIN_ORDER_QTY_ETH)
    mx = float(max_qty if max_qty is not None else settings.MAX_POSITION_QTY)
    qty = round_fn(_clamp_qty(raw_qty, min_qty=mn, max_qty=mx))
    meta["raw_qty"] = round(raw_qty, 6)
    meta["base_qty"] = qty
    meta["final_qty"] = qty
    return qty, meta


def compute_vps_add_qty(
    *,
    base_qty: float,
    round_fn,
    min_qty: float | None = None,
    max_qty: float | None = None,
    entry_type: str = "PYRAMID",
) -> tuple[float, dict[str, Any]]:
    """PYRAMID / PROFIT_ADD: add_qty = base_qty × ADD_QTY_RATIO（固定，不读 TV）."""
    bq = max(float(base_qty or 0), 0.0)
    qr = vps_add_qty_ratio()
    raw = bq * qr
    mn = float(min_qty if min_qty is not None else settings.MIN_ORDER_QTY_ETH)
    mx = float(max_qty if max_qty is not None else settings.MAX_POSITION_QTY)
    qty = round_fn(_clamp_qty(raw, min_qty=mn, max_qty=mx))
    return qty, {
        "sizing_mode": "vps_add",
        "entry_type": entry_type,
        "base_qty": round(bq, 6),
        "add_qty_ratio": round(qr, 4),
        "qty_ratio": round(qr, 4),
        "add_qty": qty,
        "final_qty": qty,
    }


def compute_vps_open_contracts(
    *,
    live_balance: float,
    initial_principal: float,
    price: float,
    tv_sl: float,
    regime: int,
    leverage: int,
    face_value: float,
    min_qty: float | None = None,
    max_qty: float | None = None,
) -> tuple[int, dict[str, Any]]:
    def _round_contracts(x: float) -> float:
        return max(int(x), 1)

    qty, meta = compute_vps_open_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        regime=regime,
        leverage=leverage,
        round_fn=_round_contracts,
        min_qty=min_qty or 1,
        max_qty=max_qty,
    )
    if meta.get("order_amount"):
        meta["notional_usd"] = round(meta["order_amount"], 4)
    meta["face_value"] = face_value
    return int(qty), meta


def compute_vps_add_contracts(
    *,
    base_qty: float,
    entry_type: str = "PYRAMID",
    min_qty: float | None = None,
    max_qty: float | None = None,
) -> tuple[int, dict[str, Any]]:
    def _round_contracts(x: float) -> float:
        return max(int(x), 1)

    qty, meta = compute_vps_add_qty(
        base_qty=base_qty,
        round_fn=_round_contracts,
        min_qty=min_qty or 1,
        max_qty=max_qty,
        entry_type=entry_type,
    )
    return int(qty), meta


def resolve_vps_entry_qty_eth(
    *,
    live_balance: float,
    initial_principal: float,
    entry_type: str,
    base_qty: float,
    price: float,
    tv_sl: float,
    regime: int,
    exchange_leverage: int,
    round_fn,
) -> tuple[float, dict]:
    if entry_type in ENTRY_TYPES_ADD:
        if base_qty <= 0:
            return 0.0, {"error": "missing_base_qty", "entry_type": entry_type}
        return compute_vps_add_qty(
            base_qty=base_qty,
            round_fn=round_fn,
            entry_type=entry_type,
        )
    return compute_vps_open_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        regime=regime,
        leverage=exchange_leverage,
        round_fn=round_fn,
    )


def resolve_vps_entry_qty_deepcoin(
    *,
    live_balance: float,
    initial_principal: float,
    entry_type: str,
    base_qty: float,
    price: float,
    tv_sl: float,
    regime: int,
    exchange_leverage: int,
    face_value: float,
) -> tuple[int, dict]:
    if entry_type in ENTRY_TYPES_ADD:
        if base_qty <= 0:
            return 0, {"error": "missing_base_qty", "entry_type": entry_type}
        return compute_vps_add_contracts(
            base_qty=base_qty,
            entry_type=entry_type,
        )
    return compute_vps_open_contracts(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        regime=regime,
        leverage=exchange_leverage,
        face_value=face_value,
    )
