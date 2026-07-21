"""Entry sizing — VPS 实盘清单 v6.5.6 (all exchanges).

Formula (authoritative):
  risk_capital = equity × 0.20          # 单笔最大亏损额
  notional_cap = equity × 5             # 最大杠杆名义上限
  risk_qty     = risk_capital / |price − stop_loss|
  lev_qty      = notional_cap / price
  theoretical  = min(risk_qty, lev_qty)
  final_qty    = min(theoretical, TV.qty) if TV.qty > 0 else theoretical
  precision    = floor(qty / step) × step

Exchange leverage always set to 5×.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from app.config import get_settings
from app.core.position_sizing import resolve_principal_sizing_base

settings = get_settings()

RISK_PCT = 0.20          # 单笔风险比例
MAX_LEVERAGE = 5         # 最大杠杆（名义上限 = equity × 5）
FIXED_MARGIN_PCT = RISK_PCT   # compat alias
FIXED_LEVERAGE = MAX_LEVERAGE  # compat alias

ENTRY_TYPES = frozenset({"OPEN"})
ENTRY_TYPES_ADD = frozenset()


def _parse_float(raw, default: float | None = None) -> float | None:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def floor_qty(qty: float, step: float = 0.001) -> float:
    q = float(qty or 0)
    st = float(step or 0.001)
    if q <= 0 or st <= 0:
        return 0.0
    return math.floor(q / st + 1e-12) * st


def parse_tv_entry_fields(payload: dict | None) -> dict[str, Any]:
    data = dict(payload or {})
    tv_qty = _parse_float(data.get("qty"))
    return {
        "entry_type": "OPEN",
        "regime": None,
        "uses_vps_sizing": True,
        "uses_tv_sizing": False,
        "tv_qty": tv_qty,
        "tv_qty1": _parse_float(data.get("qty1")),
        "tv_qty2": _parse_float(data.get("qty2")),
        "tv_qty3": _parse_float(data.get("qty3")),
        "margin_pct": RISK_PCT,
        "leverage": MAX_LEVERAGE,
        "tv_leverage": float(MAX_LEVERAGE),
        "qty_ratio": 1.0,
        "qty_ratio_source": "vps_risk20_lev5",
        "sizing_mode": "risk20_cap5x_tv_qty_cap",
    }


def _qty_step_for_symbol(symbol: str | None) -> float:
    from app.core.symbol_precision import min_qty_for
    from app.core.symbol_registry import normalize_canonical_symbol

    can = normalize_canonical_symbol(symbol)
    if can:
        return float(min_qty_for(can) or 0.001)
    return 0.001


def compute_tv_entry_qty(
    *,
    live_balance: float,
    initial_principal: float,
    price: float,
    tv_sl: float = 0.0,
    risk_pct: float = 0.0,
    leverage: float | int = MAX_LEVERAGE,
    qty_ratio: float = 1.0,
    regime: int | None = None,
    entry_type: str = "OPEN",
    round_fn: Callable[[float], float] | None = None,
    min_qty: float | None = None,
    max_qty: float | None = None,
    symbol: str | None = None,
    margin_pct: float | None = None,
    tv_qty: float | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    risk_capital/stop_dist vs notional_cap/price, then min with TV.qty.
    """
    from app.core.symbol_registry import normalize_canonical_symbol

    sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)
    if float(live_balance or 0) > 0:
        sizing_base = float(live_balance)
        sizing_source = "total_equity"

    price_f = float(price or 0)
    tv_sl_f = float(tv_sl or 0)
    lev = float(MAX_LEVERAGE)
    risk_frac = float(margin_pct if margin_pct is not None else RISK_PCT)
    can = normalize_canonical_symbol(symbol)
    step = _qty_step_for_symbol(symbol)
    mn = float(min_qty if min_qty is not None else step)
    mx = float(max_qty if max_qty is not None else getattr(settings, "MAX_POSITION_QTY", 0) or 0)
    tv_qty_f = float(tv_qty) if tv_qty is not None and float(tv_qty) > 0 else 0.0

    meta: dict[str, Any] = {
        "sizing_mode": "risk20_cap5x_tv_qty_cap",
        "entry_type": "OPEN",
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "equity": round(sizing_base, 2),
        "equity_balance": round(float(live_balance or 0), 2),
        "initial_principal": round(float(initial_principal or 0), 2),
        "leverage": int(lev),
        "tv_leverage": int(lev),
        "margin_pct": round(risk_frac * 100.0, 2),
        "margin_pct_frac": risk_frac,
        "price": round(price_f, 4),
        "tv_sl": round(tv_sl_f, 4) if tv_sl_f else None,
        "tv_qty_cap": tv_qty_f if tv_qty_f > 0 else None,
        "hard_notional_usd": None,
        "hard_cap_removed": True,
        "symbol": can,
        "qty_step": step,
        "qty_ratio": 1.0,
    }

    if price_f <= 0:
        meta["error"] = "invalid_price"
        return 0.0, meta
    if sizing_base <= 0:
        meta["error"] = "zero_equity"
        return 0.0, meta
    if tv_sl_f <= 0:
        meta["error"] = "missing_stop_loss"
        return 0.0, meta

    stop_distance = abs(price_f - tv_sl_f)
    meta["sl_distance"] = round(stop_distance, 6)
    meta["stop_distance"] = round(stop_distance, 6)
    if stop_distance <= 0:
        meta["error"] = "zero_stop_distance"
        return 0.0, meta

    risk_capital = sizing_base * risk_frac
    notional_cap = sizing_base * lev
    risk_qty = risk_capital / stop_distance
    lev_qty = notional_cap / price_f
    theoretical = min(risk_qty, lev_qty)
    binding = "risk" if risk_qty <= lev_qty else "leverage_cap"

    raw_qty = theoretical
    if tv_qty_f > 0 and tv_qty_f < raw_qty:
        raw_qty = tv_qty_f
        binding = "tv_qty_cap"

    meta["risk_capital"] = round(risk_capital, 4)
    meta["notional_cap"] = round(notional_cap, 4)
    meta["risk_qty"] = round(risk_qty, 6)
    meta["leverage_limit_qty"] = round(lev_qty, 6)
    meta["theoretical_qty"] = round(theoretical, 6)
    meta["raw_qty"] = round(raw_qty, 6)
    meta["binding"] = binding

    floored = floor_qty(raw_qty, step)
    if round_fn is not None:
        qty = float(round_fn(floored))
    else:
        qty = floored
    if mx > 0:
        qty = min(qty, mx)
    if qty > 0 and mn > 0 and qty < mn:
        meta["error"] = "below_min_qty"
        meta["final_qty"] = 0.0
        return 0.0, meta

    actual_notional = qty * price_f
    meta["margin_usd"] = round(actual_notional / lev, 4) if lev > 0 else 0.0
    meta["position_value"] = round(actual_notional, 4)
    meta["order_amount"] = round(actual_notional, 4)
    meta["notional_usd"] = round(actual_notional, 4)
    meta["effective_leverage"] = (
        round(actual_notional / sizing_base, 2) if sizing_base > 0 else 0.0
    )
    meta["base_qty"] = qty
    meta["add_qty"] = None
    meta["final_qty"] = qty
    return qty, meta


def compute_vps_open_qty(
    *,
    live_balance: float,
    initial_principal: float,
    price: float,
    tv_sl: float = 0.0,
    regime: int = 3,
    leverage: int = MAX_LEVERAGE,
    round_fn=None,
    min_qty: float | None = None,
    max_qty: float | None = None,
    symbol: str | None = None,
    risk_pct: float | None = None,
    qty_ratio: float = 1.0,
    tv_qty: float | None = None,
) -> tuple[float, dict[str, Any]]:
    return compute_tv_entry_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        round_fn=round_fn,
        min_qty=min_qty,
        max_qty=max_qty,
        symbol=symbol,
        tv_qty=tv_qty,
    )


def compute_vps_add_qty(**kwargs) -> tuple[float, dict[str, Any]]:
    live_balance = kwargs.get("live_balance")
    price = kwargs.get("price")
    if live_balance is None or price is None:
        return 0.0, {"sizing_mode": "risk20_cap5x_tv_qty_cap", "error": "add_disabled", "final_qty": 0.0}
    return compute_tv_entry_qty(
        live_balance=float(live_balance),
        initial_principal=float(kwargs.get("initial_principal") or live_balance or 0),
        price=float(price),
        tv_sl=float(kwargs.get("tv_sl") or 0),
        round_fn=kwargs.get("round_fn"),
        min_qty=kwargs.get("min_qty"),
        max_qty=kwargs.get("max_qty"),
        symbol=kwargs.get("symbol"),
        tv_qty=kwargs.get("tv_qty"),
    )


def compute_vps_open_contracts(
    *,
    live_balance: float,
    initial_principal: float,
    price: float,
    tv_sl: float = 0.0,
    regime: int = 3,
    leverage: int = MAX_LEVERAGE,
    face_value: float = 0.1,
    min_qty: float | None = None,
    max_qty: float | None = None,
    symbol: str | None = None,
    risk_pct: float | None = None,
    qty_ratio: float = 1.0,
    tv_qty: float | None = None,
) -> tuple[int, dict[str, Any]]:
    fv = max(float(face_value or 0.1), 1e-9)
    # TV qty for deepcoin may already be contracts — treat as ETH-equiv if < large
    eth_qty, meta = compute_vps_open_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        round_fn=lambda x: x,
        min_qty=None,
        max_qty=max_qty,
        symbol=symbol,
        tv_qty=tv_qty,
    )
    contracts = int(math.floor(float(eth_qty) / fv + 1e-12)) if eth_qty > 0 else 0
    if min_qty and contracts > 0 and contracts < int(min_qty):
        meta["error"] = "below_min_qty"
        contracts = 0
    meta["face_value"] = fv
    meta["eth_equivalent"] = round(eth_qty, 6)
    meta["final_qty"] = contracts
    meta["base_qty"] = contracts
    if contracts > 0 and price:
        meta["notional_usd"] = round(contracts * fv * float(price), 4)
        meta["position_value"] = meta["notional_usd"]
    return contracts, meta


def compute_vps_add_contracts(**kwargs) -> tuple[int, dict[str, Any]]:
    fv = max(float(kwargs.get("face_value") or 0.1), 1e-9)
    eth_qty, meta = compute_vps_add_qty(**{k: v for k, v in kwargs.items() if k != "face_value"})
    contracts = int(math.floor(float(eth_qty) / fv + 1e-12)) if eth_qty > 0 else 0
    meta["face_value"] = fv
    meta["final_qty"] = contracts
    meta["add_qty"] = contracts
    return contracts, meta


def resolve_vps_entry_qty_eth(
    *,
    live_balance: float,
    initial_principal: float,
    entry_type: str = "OPEN",
    base_qty: float = 0.0,
    price: float,
    tv_sl: float = 0.0,
    regime: int = 3,
    exchange_leverage: int = MAX_LEVERAGE,
    round_fn,
    tv_qty_ratio: float | None = None,
    qty_ratio_source: str = "vps_risk20_lev5",
    symbol: str | None = None,
    min_qty: float | None = None,
    risk_pct: float | None = None,
    tv_qty: float | None = None,
) -> tuple[float, dict]:
    return compute_vps_open_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        round_fn=round_fn,
        symbol=symbol,
        min_qty=min_qty,
        tv_qty=tv_qty,
    )


def resolve_vps_entry_qty_deepcoin(
    *,
    live_balance: float,
    initial_principal: float,
    entry_type: str = "OPEN",
    base_qty: float = 0.0,
    price: float,
    tv_sl: float = 0.0,
    regime: int = 3,
    exchange_leverage: int = MAX_LEVERAGE,
    face_value: float = 0.1,
    tv_qty_ratio: float | None = None,
    qty_ratio_source: str = "vps_risk20_lev5",
    symbol: str | None = None,
    risk_pct: float | None = None,
    tv_qty: float | None = None,
) -> tuple[int, dict]:
    return compute_vps_open_contracts(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        face_value=face_value,
        symbol=symbol,
        tv_qty=tv_qty,
    )


def regime_add_qty_ratio(regime: int) -> float:
    return 0.0


def max_add_times_for_regime(regime: int) -> int:
    return 0


def resolve_tv_add_qty_ratio(data: dict | None, regime: int) -> tuple[float, str]:
    return 0.0, "add_disabled"
