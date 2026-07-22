"""Entry sizing — RISK20 + notional5 + TV qty adjusted to VPS stop distance.

Authoritative formula (stateless pure function, computed once at open):
  sizing_base         = 合约本金余额 (futures total equity; fallback initial_principal)
  risk_capital        = sizing_base × 0.20
  notional_cap        = sizing_base × 5          # NEVER haircut; NEVER (base×0.20×5)/price alone
  vps_stop_dist       = |price − VPS initialStop|  # initialStop = entry±1.5×ATR
  tv_implied_dist     = |price − TV.stop_loss|
  adjust_coef         = tv_implied_dist / vps_stop_dist
  adjusted_tv_qty_cap = TV.qty × adjust_coef
  theoretical         = min(risk_capital/vps_stop_dist, notional_cap/price, adjusted_tv_qty_cap)
  qty                 = floor(theoretical to exchange step)

TV.stop_loss is ONLY an input to adjust_coef — never the exchange stop price.
Breathing engine still places stops at VPS initialStop / currentStop.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from app.config import get_settings
from app.core.position_sizing import resolve_principal_sizing_base

settings = get_settings()

RISK_PCT = 0.20
MAX_LEVERAGE = 5
FIXED_MARGIN_PCT = RISK_PCT
FIXED_LEVERAGE = MAX_LEVERAGE
SIZING_MODE = "risk20_cap5x_tv_qty_cap"
# When TV.qty is strategy.equity-inflated (e.g. 8.6e8), adjusted_tv_qty must not
# silently disappear from the min() as a useful cap — we still require tv_qty>0 as
# signal presence, but ignore absurd caps so risk∩notional bind.
ABSURD_TV_QTY_VS_CAPS = 50.0
# Legacy alias kept for import compatibility; live notional is always full ×5.
NOTIONAL_MARGIN_HAIRCUT = 1.0

ENTRY_TYPES = frozenset({"OPEN"})
ENTRY_TYPES_ADD = frozenset()  # pyramiding disabled


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
        "qty_ratio_source": "vps_risk20_notional5",
        "sizing_mode": SIZING_MODE,
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
    tv_stop_loss: float | None = None,
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
    """Independent per-open sizing — no history / add_count.

    ``tv_sl`` = VPS ``initialStop`` (risk-distance denominator).
    ``tv_stop_loss`` = TradingView ``stop_loss`` (adjustment coefficient only).
    """
    from app.core.symbol_registry import normalize_canonical_symbol

    # 铁律：永远用合约本金余额（U本位合约总权益），不是可用保证金、不是旧 (×0.20×5)/price。
    if float(live_balance or 0) > 0:
        sizing_base = float(live_balance)
        sizing_source = "contract_equity"
    else:
        sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)

    price_f = float(price or 0)
    vps_stop_f = float(tv_sl or 0)
    tv_sl_f = float(tv_stop_loss) if tv_stop_loss is not None and float(tv_stop_loss or 0) > 0 else 0.0
    lev = float(MAX_LEVERAGE)
    risk_frac = float(margin_pct if margin_pct is not None else RISK_PCT)
    can = normalize_canonical_symbol(symbol)
    step = _qty_step_for_symbol(symbol)
    mn = float(min_qty if min_qty is not None else step)
    mx = float(max_qty if max_qty is not None else getattr(settings, "MAX_POSITION_QTY", 0) or 0)
    tv_qty_f = float(tv_qty) if tv_qty is not None and float(tv_qty) > 0 else 0.0

    meta: dict[str, Any] = {
        "sizing_mode": SIZING_MODE,
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
        "tv_sl": round(vps_stop_f, 4) if vps_stop_f else None,
        "vps_initial_stop": round(vps_stop_f, 4) if vps_stop_f else None,
        "tv_stop_loss": round(tv_sl_f, 4) if tv_sl_f else None,
        "tv_qty_ref": tv_qty_f if tv_qty_f > 0 else None,
        "tv_qty_cap": None,
        "hard_notional_usd": None,
        "hard_cap_removed": True,
        "symbol": can,
        "qty_step": step,
        "qty_ratio": 1.0,
        "binding": "risk20_notional5_tv_qty_adj",
        "adjust_coef": None,
    }

    if price_f <= 0:
        meta["error"] = "invalid_price"
        return 0.0, meta
    if sizing_base <= 0:
        meta["error"] = "zero_equity"
        return 0.0, meta
    if vps_stop_f <= 0:
        meta["error"] = "missing_stop"
        return 0.0, meta
    vps_dist = abs(price_f - vps_stop_f)
    if vps_dist <= 0:
        meta["error"] = "zero_stop_distance"
        return 0.0, meta
    if tv_qty_f <= 0:
        meta["error"] = "missing_tv_qty"
        return 0.0, meta
    if tv_sl_f <= 0:
        meta["error"] = "missing_tv_stop_loss"
        return 0.0, meta
    tv_dist = abs(price_f - tv_sl_f)
    if tv_dist <= 0:
        meta["error"] = "zero_tv_stop_distance"
        return 0.0, meta

    adjust_coef = tv_dist / vps_dist
    adjusted_tv_qty = tv_qty_f * adjust_coef

    risk_capital = sizing_base * risk_frac
    notional_cap = sizing_base * lev  # 合约本金余额 × 5，无折损
    qty_by_risk = risk_capital / vps_dist
    qty_by_notional = notional_cap / price_f
    tv_qty_ignored_absurd = False
    cap_ref = max(qty_by_risk, qty_by_notional)
    if (
        cap_ref > 0
        and adjusted_tv_qty > cap_ref * ABSURD_TV_QTY_VS_CAPS
    ):
        # Pine strategy.equity inflation: TV.qty is not a meaningful cap.
        theoretical = min(qty_by_risk, qty_by_notional)
        tv_qty_ignored_absurd = True
    else:
        theoretical = min(qty_by_risk, qty_by_notional, adjusted_tv_qty)

    # Hard ceiling: never exceed 合约本金 × 5 notional (天文数字兜底).
    if theoretical * price_f > notional_cap + 1e-9:
        theoretical = qty_by_notional

    meta["risk_capital"] = round(risk_capital, 4)
    meta["notional_cap"] = round(notional_cap, 4)
    meta["nominal_value"] = round(notional_cap, 4)
    meta["notional_margin_haircut"] = 1.0
    meta["sl_distance"] = round(vps_dist, 6)
    meta["stop_distance"] = meta["sl_distance"]
    meta["vps_stop_distance"] = round(vps_dist, 6)
    meta["tv_implied_stop_distance"] = round(tv_dist, 6)
    meta["adjust_coef"] = round(adjust_coef, 8)
    meta["tv_qty_cap"] = round(adjusted_tv_qty, 6)
    meta["adjusted_tv_qty_cap"] = round(adjusted_tv_qty, 6)
    meta["tv_qty_ignored_absurd"] = tv_qty_ignored_absurd
    meta["qty_by_risk"] = round(qty_by_risk, 6)
    meta["qty_by_notional"] = round(qty_by_notional, 6)
    meta["theoretical_qty"] = round(theoretical, 6)
    meta["raw_qty"] = round(theoretical, 6)
    meta["candidate_qty_by_risk"] = meta["qty_by_risk"]
    meta["candidate_qty_by_notional"] = meta["qty_by_notional"]
    meta["candidate_qty_by_tv_adj"] = meta["adjusted_tv_qty_cap"]

    if tv_qty_ignored_absurd:
        if qty_by_risk <= qty_by_notional + 1e-12:
            meta["binding"] = "stop_risk"
        else:
            meta["binding"] = "notional_cap"
    elif qty_by_risk <= qty_by_notional + 1e-12 and qty_by_risk <= adjusted_tv_qty + 1e-12:
        meta["binding"] = "stop_risk"
    elif qty_by_notional <= adjusted_tv_qty + 1e-12:
        meta["binding"] = "notional_cap"
    else:
        meta["binding"] = "tv_qty_cap_adjusted"

    floored = floor_qty(theoretical, step)
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
    tv_stop_loss: float | None = None,
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
        tv_stop_loss=tv_stop_loss,
        round_fn=round_fn,
        min_qty=min_qty,
        max_qty=max_qty,
        symbol=symbol,
        tv_qty=tv_qty,
    )


def compute_vps_add_qty(**kwargs) -> tuple[float, dict[str, Any]]:
    return 0.0, {"sizing_mode": SIZING_MODE, "error": "add_disabled", "final_qty": 0.0}


def compute_vps_open_contracts(
    *,
    live_balance: float,
    initial_principal: float,
    price: float,
    tv_sl: float = 0.0,
    tv_stop_loss: float | None = None,
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
    eth_qty, meta = compute_vps_open_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        tv_stop_loss=tv_stop_loss,
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
    return 0, {"sizing_mode": SIZING_MODE, "error": "add_disabled", "final_qty": 0}


def resolve_vps_entry_qty_eth(
    *,
    live_balance: float,
    initial_principal: float,
    entry_type: str = "OPEN",
    base_qty: float = 0.0,
    price: float,
    tv_sl: float = 0.0,
    tv_stop_loss: float | None = None,
    regime: int = 3,
    exchange_leverage: int = MAX_LEVERAGE,
    round_fn,
    tv_qty_ratio: float | None = None,
    qty_ratio_source: str = "vps_risk20_notional5",
    symbol: str | None = None,
    min_qty: float | None = None,
    risk_pct: float | None = None,
    tv_qty: float | None = None,
) -> tuple[float, dict]:
    et = str(entry_type or "OPEN").upper()
    if et in ("PYRAMID", "PROFIT_ADD", "ADD"):
        return 0.0, {"sizing_mode": SIZING_MODE, "error": "add_disabled", "final_qty": 0.0}
    return compute_vps_open_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        tv_stop_loss=tv_stop_loss,
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
    tv_stop_loss: float | None = None,
    regime: int = 3,
    exchange_leverage: int = MAX_LEVERAGE,
    face_value: float = 0.1,
    tv_qty_ratio: float | None = None,
    qty_ratio_source: str = "vps_risk20_notional5",
    symbol: str | None = None,
    risk_pct: float | None = None,
    tv_qty: float | None = None,
) -> tuple[int, dict]:
    et = str(entry_type or "OPEN").upper()
    if et in ("PYRAMID", "PROFIT_ADD", "ADD"):
        return 0, {"sizing_mode": SIZING_MODE, "error": "add_disabled", "final_qty": 0}
    return compute_vps_open_contracts(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        tv_stop_loss=tv_stop_loss,
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
