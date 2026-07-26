"""Entry sizing — equity × margin_pct × leverage = notional.

Default (legacy hardcode): 20% margin × 5× leverage = 1× equity notional.
Per-user overrides come from admin trading-control (margin_pct_frac / leverage).

Authoritative formula (stateless pure function, computed once at open):
  sizing_base  = futures total equity (fallback initial_principal)
  margin_usd   = sizing_base × margin_pct
  notional     = margin_usd × leverage
  qty          = floor(notional / price to exchange step)

TV.qty / TV.stop_loss / VPS initialStop 不参与下单数量（止损价仍由呼吸引擎用 VPS ATR）。
TV.qty/qty1-3 可缺省，完全忽略；荒谬天文数字不影响仓位。
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
SIZING_MODE = "margin20_lev5_notional1x"
# Compat: absurd-TV gate no longer changes qty (fixed 1× notional); keep constant for imports.
ABSURD_TV_QTY_VS_CAPS = 50.0
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
    atr = _parse_float(data.get("atr"))
    margin = _parse_float(data.get("margin_pct_frac"), RISK_PCT)
    if margin is None or margin <= 0:
        margin = RISK_PCT
    if margin > 1.0 + 1e-12:
        margin = margin / 100.0
    lev_raw = data.get("entry_leverage", data.get("leverage"))
    lev = _parse_float(lev_raw, float(MAX_LEVERAGE))
    if lev is None or lev <= 0:
        lev = float(MAX_LEVERAGE)
    lev_i = int(lev)
    return {
        "entry_type": "OPEN",
        "regime": None,
        "uses_vps_sizing": True,
        "uses_tv_sizing": False,
        "tv_qty": tv_qty,
        "tv_qty1": _parse_float(data.get("qty1")),
        "tv_qty2": _parse_float(data.get("qty2")),
        "tv_qty3": _parse_float(data.get("qty3")),
        "atr": atr,
        "margin_pct": float(margin),
        "leverage": lev_i,
        "tv_leverage": float(lev_i),
        "qty_ratio": 1.0,
        "qty_ratio_source": "vps_admin_sizing",
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
    exchange_leverage: float | int | None = None,
) -> tuple[float, dict[str, Any]]:
    """Per-open sizing: equity × margin_pct × leverage.

    Defaults remain 20% × 5× when overrides are omitted.
    ``tv_sl`` / ``tv_stop_loss`` are logged only; breathing engine places the real stop.
    ``tv_qty`` / qty1-3 are ignored for order size (optional legacy fields if present).
    """
    from app.core.symbol_registry import normalize_canonical_symbol

    if float(live_balance or 0) > 0:
        sizing_base = float(live_balance)
        sizing_source = "contract_equity"
    else:
        sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)

    price_f = float(price or 0)
    vps_stop_f = float(tv_sl or 0)
    tv_sl_f = float(tv_stop_loss) if tv_stop_loss is not None and float(tv_stop_loss or 0) > 0 else 0.0
    lev_in = exchange_leverage if exchange_leverage is not None else leverage
    try:
        lev = float(lev_in) if lev_in is not None and float(lev_in) > 0 else float(MAX_LEVERAGE)
    except (TypeError, ValueError):
        lev = float(MAX_LEVERAGE)
    # risk_pct is legacy alias for margin_pct
    margin_in = margin_pct if margin_pct is not None else (risk_pct if risk_pct else None)
    try:
        risk_frac = float(margin_in) if margin_in is not None else float(RISK_PCT)
    except (TypeError, ValueError):
        risk_frac = float(RISK_PCT)
    if risk_frac > 1.0 + 1e-12:
        risk_frac = risk_frac / 100.0
    risk_frac = max(0.01, min(1.0, risk_frac))
    lev = max(1.0, min(125.0, lev))
    binding = f"margin{int(round(risk_frac * 100))}_lev{int(lev)}"
    can = normalize_canonical_symbol(symbol)
    step = _qty_step_for_symbol(symbol)
    mn = float(min_qty if min_qty is not None else step)
    mx = float(max_qty if max_qty is not None else getattr(settings, "MAX_POSITION_QTY", 0) or 0)
    # Optional legacy field — never gates or sizes the order
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
        "tv_qty_ignored": True,
        "tv_qty_cap": None,
        "hard_notional_usd": None,
        "hard_cap_removed": True,
        "symbol": can,
        "qty_step": step,
        "qty_ratio": 1.0,
        "binding": binding,
        "adjust_coef": None,
    }

    if price_f <= 0:
        meta["error"] = "invalid_price"
        return 0.0, meta
    if sizing_base <= 0:
        meta["error"] = "zero_equity"
        return 0.0, meta

    # equity × margin_pct × leverage（不读 TV qty / 不反推系数）
    margin_usd = sizing_base * risk_frac
    notional_target = margin_usd * lev
    # 内测闸门：E2E_FORCE_NOTIONAL_USD>0 时压到约最小名义（生产默认 0，不生效）
    try:
        e2e_notional = float(getattr(get_settings(), "E2E_FORCE_NOTIONAL_USD", 0) or 0)
    except Exception:
        e2e_notional = 0.0
    if e2e_notional > 0:
        notional_target = min(float(notional_target), e2e_notional)
        margin_usd = notional_target / lev if lev > 0 else margin_usd
        meta["e2e_force_notional_usd"] = e2e_notional
        meta["binding"] = "e2e_force_notional"
    theoretical = notional_target / price_f

    vps_dist = abs(price_f - vps_stop_f) if vps_stop_f > 0 else 0.0
    tv_dist = abs(price_f - tv_sl_f) if tv_sl_f > 0 else 0.0

    meta["risk_capital"] = round(margin_usd, 4)
    meta["margin_usd_target"] = round(margin_usd, 4)
    meta["notional_cap"] = round(notional_target, 4)
    meta["nominal_value"] = round(notional_target, 4)
    meta["notional_target"] = round(notional_target, 4)
    meta["notional_margin_haircut"] = 1.0
    meta["sl_distance"] = round(vps_dist, 6) if vps_dist else None
    meta["stop_distance"] = meta["sl_distance"]
    meta["vps_stop_distance"] = round(vps_dist, 6) if vps_dist else None
    meta["tv_implied_stop_distance"] = round(tv_dist, 6) if tv_dist else None
    meta["adjust_coef"] = None
    meta["tv_qty_cap"] = None
    meta["adjusted_tv_qty_cap"] = None
    meta["tv_qty_ignored_absurd"] = False
    meta["qty_by_risk"] = None
    meta["qty_by_notional"] = round(theoretical, 6)
    meta["theoretical_qty"] = round(theoretical, 6)
    meta["raw_qty"] = round(theoretical, 6)
    meta["candidate_qty_by_risk"] = None
    meta["candidate_qty_by_notional"] = meta["qty_by_notional"]
    meta["candidate_qty_by_tv_adj"] = None
    if not meta.get("e2e_force_notional_usd"):
        meta["binding"] = binding

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

    # Hard ceiling: never exceed sized notional target
    if qty * price_f > notional_target + 1e-6:
        qty = floor_qty(notional_target / price_f, step)
        if round_fn is not None:
            qty = float(round_fn(qty))

    actual_notional = qty * price_f
    # Exchange MIN_NOTIONAL pre-reject (ETH≈20 / XAU≈5)
    try:
        from app.core.symbol_registry import symbol_meta
        min_notional = float(symbol_meta(can).get("min_notional") or 0)
    except Exception:
        min_notional = 0.0
    meta["min_notional"] = min_notional or None
    if qty > 0 and min_notional > 0 and actual_notional + 1e-9 < min_notional:
        meta["error"] = "below_min_notional"
        meta["final_qty"] = 0.0
        meta["notional_usd"] = round(actual_notional, 4)
        return 0.0, meta

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
        leverage=leverage,
        margin_pct=risk_pct,
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
        leverage=leverage,
        risk_pct=risk_pct,
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
    qty_ratio_source: str = "vps_margin20_lev5",
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
        leverage=int(exchange_leverage or MAX_LEVERAGE),
        risk_pct=risk_pct,
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
    qty_ratio_source: str = "vps_margin20_lev5",
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
        leverage=int(exchange_leverage or MAX_LEVERAGE),
        risk_pct=risk_pct,
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
