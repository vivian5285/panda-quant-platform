"""TV-driven entry sizing — single formula for OPEN and ADD (all exchanges).

Formula (VPS does NOT recompute risk_pct / qty_ratio / leverage):
  stop_distance   = |price - tv_sl|
  risk_amount     = equity × (risk_pct / 100)
  theoretical     = risk_amount / stop_distance
  leverage_limit  = equity × leverage / price
  hard_cap        = HARD_NOTIONAL_USD / price   (default 50000)
  final_qty       = min(theoretical, leverage_limit, hard_cap) × qty_ratio
  precision       = floor(final_qty / step) × step   (ETH 0.001 / XAU 0.01)

Legacy REGIME_MARGIN / VPS_RISK_PCT × scale paths are removed from live placement.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from app.config import get_settings
from app.core.position_sizing import resolve_principal_sizing_base
from app.core.regime_utils import clamp_regime

settings = get_settings()

ENTRY_TYPES = frozenset({"OPEN", "PYRAMID", "PROFIT_ADD"})
ENTRY_TYPES_ADD = frozenset({"PYRAMID", "PROFIT_ADD"})

# Per-order notional hard upper bound (USDT)
HARD_NOTIONAL_USD = float(getattr(settings, "HARD_NOTIONAL_CAP_USD", 50000) or 50000)


def _parse_float(raw, default: float | None = None) -> float | None:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def regime_scale(regime: int) -> float:
    """Deprecated legacy helper — not used for live sizing."""
    r = clamp_regime(int(regime or 3))
    return {
        1: float(settings.REGIME_SCALE_1),
        2: float(settings.REGIME_SCALE_2),
        3: float(settings.REGIME_SCALE_3),
        4: float(settings.REGIME_SCALE_4),
    }.get(r, 1.0)


def regime_margin_coeff(regime: int) -> float:
    """Deprecated — REGIME_MARGIN no longer drives live qty."""
    r = clamp_regime(int(regime or 3))
    return {
        1: float(getattr(settings, "REGIME_MARGIN_1", 0.08) or 0.08),
        2: float(getattr(settings, "REGIME_MARGIN_2", 0.14) or 0.14),
        3: float(getattr(settings, "REGIME_MARGIN_3", 0.20) or 0.20),
        4: float(getattr(settings, "REGIME_MARGIN_4", 0.26) or 0.26),
    }.get(r, float(getattr(settings, "REGIME_MARGIN_3", 0.20) or 0.20))


def regime_add_qty_ratio(regime: int) -> float:
    """Fallback ADD qty_ratio when TV omits it (align Pine defaults)."""
    r = clamp_regime(int(regime or 3))
    return {
        1: float(getattr(settings, "ADD_RATIO_REG1", 0.0) or 0.0),
        2: float(getattr(settings, "ADD_RATIO_REG2", 0.3) or 0.3),
        3: float(getattr(settings, "ADD_RATIO_REG3", 0.5) or 0.5),
        4: float(getattr(settings, "ADD_RATIO_REG4", 0.7) or 0.7),
    }.get(r, float(settings.ADD_QTY_RATIO or 0.5))


def max_add_times_for_regime(regime: int) -> int:
    r = clamp_regime(int(regime or 3))
    key_map = {
        1: "MAX_ADD_TIMES_REG1",
        2: "MAX_ADD_TIMES_REG2",
        3: "MAX_ADD_TIMES_REG3",
        4: "MAX_ADD_TIMES_REG4",
    }
    attr = key_map.get(r, "MAX_ADD_TIMES")
    fallback = int(getattr(settings, "MAX_ADD_TIMES", 2) or 2)
    return max(int(getattr(settings, attr, fallback) or fallback), 0)


def resolve_tv_add_qty_ratio(data: dict | None, regime: int) -> tuple[float, str]:
    raw = _parse_float((data or {}).get("qty_ratio"))
    if raw is not None:
        return max(raw, 0.0), "tv_qty_ratio"
    return regime_add_qty_ratio(regime), "regime_default"


def effective_vps_risk_pct(regime: int) -> tuple[float, dict[str, Any]]:
    """Deprecated legacy helper — live path uses TV risk_pct only."""
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
        "deprecated": True,
    }


def floor_qty(qty: float, step: float = 0.001) -> float:
    """floor(qty / step) * step — ETH step 0.001, XAU 0.01."""
    q = float(qty or 0)
    st = float(step or 0.001)
    if q <= 0 or st <= 0:
        return 0.0
    return math.floor(q / st + 1e-12) * st


def parse_tv_entry_fields(payload: dict | None) -> dict[str, Any]:
    """Parse TV sizing params — risk_pct / qty_ratio / leverage are authoritative."""
    data = dict(payload or {})
    entry_type = str(data.get("entry_type") or "OPEN").upper().strip()
    if entry_type not in ENTRY_TYPES:
        entry_type = "OPEN"
    regime = _parse_regime(data.get("regime"))
    risk_pct = _parse_float(data.get("risk_pct"))
    leverage = _parse_float(data.get("leverage"))
    fields: dict[str, Any] = {
        "entry_type": entry_type,
        "regime": regime,
        "uses_vps_sizing": True,
        "uses_tv_sizing": True,
        "tv_qty_ratio_ignored": False,
    }
    if risk_pct is not None:
        fields["risk_pct"] = round(float(risk_pct), 6)
    if leverage is not None and float(leverage) > 0:
        fields["leverage"] = int(round(float(leverage)))
        fields["tv_leverage"] = float(leverage)

    if entry_type in ENTRY_TYPES_ADD:
        r = regime if regime is not None else 3
        qty_ratio, ratio_source = resolve_tv_add_qty_ratio(data, r)
        fields["qty_ratio"] = round(qty_ratio, 4)
        fields["add_qty_ratio"] = round(qty_ratio, 4)
        fields["qty_ratio_source"] = ratio_source
        fields["max_add_times"] = max_add_times_for_regime(r)
    else:
        qr = _parse_float(data.get("qty_ratio"), 1.0)
        fields["qty_ratio"] = round(max(float(qr or 1.0), 0.0), 4)
        fields["qty_ratio_source"] = "tv_qty_ratio" if data.get("qty_ratio") is not None else "open_default_1"
    return fields


def _parse_regime(raw) -> int | None:
    try:
        return clamp_regime(int(raw)) if raw is not None else None
    except (TypeError, ValueError):
        return None


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
    tv_sl: float,
    risk_pct: float,
    leverage: float | int,
    qty_ratio: float = 1.0,
    regime: int | None = None,
    entry_type: str = "OPEN",
    round_fn: Callable[[float], float] | None = None,
    min_qty: float | None = None,
    max_qty: float | None = None,
    symbol: str | None = None,
    hard_notional_usd: float | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    Unique TV sizing formula (OPEN and ADD).
    risk_pct is percent units (e.g. 0.81 = 0.81% of equity).
    """
    from app.core.symbol_registry import normalize_canonical_symbol

    sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)
    if float(live_balance or 0) > 0:
        sizing_base = float(live_balance)
        sizing_source = "total_equity"

    price_f = float(price or 0)
    tv_sl_f = float(tv_sl or 0)
    risk_f = float(risk_pct or 0)
    lev = max(float(leverage or 0), 0.0)
    qr = max(float(qty_ratio or 0), 0.0)
    hard_cap_usd = float(hard_notional_usd if hard_notional_usd is not None else HARD_NOTIONAL_USD)
    can = normalize_canonical_symbol(symbol)
    step = _qty_step_for_symbol(symbol)
    mn = float(min_qty if min_qty is not None else step)
    mx = float(max_qty if max_qty is not None else getattr(settings, "MAX_POSITION_QTY", 0) or 0)

    meta: dict[str, Any] = {
        "sizing_mode": "tv_risk_formula",
        "entry_type": str(entry_type or "OPEN").upper(),
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "equity": round(sizing_base, 2),
        "equity_balance": round(float(live_balance or 0), 2),
        "initial_principal": round(float(initial_principal or 0), 2),
        "leverage": int(lev) if lev > 0 else 0,
        "price": round(price_f, 4),
        "tv_sl": round(tv_sl_f, 4),
        "risk_pct": round(risk_f, 6),
        "qty_ratio": round(qr, 4),
        "hard_notional_usd": hard_cap_usd,
        "symbol": can,
        "qty_step": step,
    }
    if regime is not None:
        meta["regime"] = clamp_regime(int(regime))

    if price_f <= 0:
        meta["error"] = "invalid_price"
        return 0.0, meta
    if tv_sl_f <= 0:
        meta["error"] = "missing_tv_sl"
        return 0.0, meta
    if risk_f <= 0:
        meta["error"] = "missing_risk_pct"
        return 0.0, meta
    if lev <= 0:
        meta["error"] = "missing_leverage"
        return 0.0, meta
    if qr <= 0:
        meta["error"] = "zero_qty_ratio"
        return 0.0, meta

    stop_distance = abs(price_f - tv_sl_f)
    meta["sl_distance"] = round(stop_distance, 6)
    meta["stop_distance"] = round(stop_distance, 6)
    if stop_distance <= 0:
        meta["error"] = "zero_stop_distance"
        return 0.0, meta

    risk_amount = sizing_base * (risk_f / 100.0)
    theoretical = risk_amount / stop_distance
    leverage_limit = sizing_base * lev / price_f
    hard_cap_qty = hard_cap_usd / price_f
    capped = min(theoretical, leverage_limit, hard_cap_qty)
    raw_qty = capped * qr

    meta["risk_amount"] = round(risk_amount, 6)
    meta["theoretical_qty"] = round(theoretical, 6)
    meta["leverage_limit_qty"] = round(leverage_limit, 6)
    meta["hard_cap_qty"] = round(hard_cap_qty, 6)
    meta["capped_qty"] = round(capped, 6)
    meta["raw_qty"] = round(raw_qty, 6)
    meta["binding"] = (
        "theoretical" if capped == theoretical
        else ("leverage" if capped == leverage_limit else "hard_cap")
    )

    floored = floor_qty(raw_qty, step)
    if round_fn is not None:
        qty = float(round_fn(floored))
    else:
        qty = floored
    if mx > 0:
        qty = min(qty, mx)
    if qty > 0 and mn > 0 and qty < mn:
        # Below exchange min — refuse rather than bump (would oversize risk)
        meta["error"] = "below_min_qty"
        meta["final_qty"] = 0.0
        return 0.0, meta

    notional = qty * price_f
    meta["margin_usd"] = round(notional / lev, 4) if lev > 0 else 0.0
    meta["position_value"] = round(notional, 4)
    meta["order_amount"] = round(notional, 4)
    meta["notional_usd"] = round(notional, 4)
    meta["base_qty"] = qty if str(entry_type or "").upper() == "OPEN" else None
    meta["add_qty"] = qty if str(entry_type or "").upper() in ENTRY_TYPES_ADD else None
    meta["add_qty_ratio"] = round(qr, 4)
    meta["final_qty"] = qty
    return qty, meta


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
    symbol: str | None = None,
    risk_pct: float | None = None,
    qty_ratio: float = 1.0,
) -> tuple[float, dict[str, Any]]:
    """OPEN — TV risk formula (risk_pct required)."""
    return compute_tv_entry_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        risk_pct=float(risk_pct or 0),
        leverage=leverage,
        qty_ratio=qty_ratio if qty_ratio is not None else 1.0,
        regime=regime,
        entry_type="OPEN",
        round_fn=round_fn,
        min_qty=min_qty,
        max_qty=max_qty,
        symbol=symbol,
    )


def compute_vps_add_qty(
    *,
    base_qty: float,
    tv_qty_ratio: float,
    round_fn,
    min_qty: float | None = None,
    max_qty: float | None = None,
    entry_type: str = "PYRAMID",
    qty_ratio_source: str = "tv_qty_ratio",
    regime: int | None = None,
    # New formula kwargs (preferred)
    live_balance: float | None = None,
    initial_principal: float | None = None,
    price: float | None = None,
    tv_sl: float | None = None,
    risk_pct: float | None = None,
    leverage: float | int | None = None,
    symbol: str | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    ADD — same TV formula × qty_ratio.
    Legacy base_qty×ratio path removed when price/tv_sl/risk_pct/leverage provided.
    """
    qr = max(float(tv_qty_ratio or 0), 0.0)
    if (
        live_balance is not None
        and price is not None
        and tv_sl is not None
        and risk_pct is not None
        and leverage is not None
    ):
        qty, meta = compute_tv_entry_qty(
            live_balance=float(live_balance),
            initial_principal=float(initial_principal or live_balance or 0),
            price=float(price),
            tv_sl=float(tv_sl),
            risk_pct=float(risk_pct),
            leverage=leverage,
            qty_ratio=qr,
            regime=regime,
            entry_type=entry_type,
            round_fn=round_fn,
            min_qty=min_qty,
            max_qty=max_qty,
            symbol=symbol,
        )
        meta["qty_ratio_source"] = qty_ratio_source
        meta["legacy_base_qty"] = round(float(base_qty or 0), 6)
        return qty, meta

    # Fallback only for unit tests that still pass base_qty alone — mark deprecated
    bq = max(float(base_qty or 0), 0.0)
    raw = bq * qr
    step = float(min_qty if min_qty is not None else 0.001)
    qty = float(round_fn(floor_qty(raw, step))) if qr > 0 else 0.0
    meta = {
        "sizing_mode": "legacy_base_x_ratio_deprecated",
        "entry_type": entry_type,
        "base_qty": round(bq, 6),
        "add_qty_ratio": round(qr, 4),
        "qty_ratio": round(qr, 4),
        "qty_ratio_source": qty_ratio_source,
        "add_qty": qty,
        "final_qty": qty,
        "error": "legacy_add_path" if qr > 0 else "zero_qty_ratio",
    }
    if regime is not None:
        meta["regime"] = clamp_regime(int(regime))
        meta["max_add_times"] = max_add_times_for_regime(int(regime))
    if qr <= 0:
        meta["error"] = "zero_qty_ratio"
    return qty, meta


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
    symbol: str | None = None,
    risk_pct: float | None = None,
    qty_ratio: float = 1.0,
) -> tuple[int, dict[str, Any]]:
    fv = max(float(face_value or 0.1), 1e-9)

    def _round_contracts(x: float) -> float:
        # x is ETH-equivalent qty from formula; convert to contracts
        return max(int(math.floor(float(x) / fv + 1e-12)), 0)

    eth_qty, meta = compute_vps_open_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        regime=regime,
        leverage=leverage,
        round_fn=lambda x: x,
        min_qty=None,
        max_qty=max_qty,
        symbol=symbol,
        risk_pct=risk_pct,
        qty_ratio=qty_ratio,
    )
    contracts = int(_round_contracts(eth_qty)) if eth_qty > 0 else 0
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


def compute_vps_add_contracts(
    *,
    base_qty: float,
    tv_qty_ratio: float,
    entry_type: str = "PYRAMID",
    min_qty: float | None = None,
    max_qty: float | None = None,
    qty_ratio_source: str = "tv_qty_ratio",
    regime: int | None = None,
    live_balance: float | None = None,
    initial_principal: float | None = None,
    price: float | None = None,
    tv_sl: float | None = None,
    risk_pct: float | None = None,
    leverage: float | int | None = None,
    face_value: float = 0.1,
    symbol: str | None = None,
) -> tuple[int, dict[str, Any]]:
    fv = max(float(face_value or 0.1), 1e-9)
    eth_qty, meta = compute_vps_add_qty(
        base_qty=base_qty,
        tv_qty_ratio=tv_qty_ratio,
        round_fn=lambda x: x,
        min_qty=None,
        max_qty=max_qty,
        entry_type=entry_type,
        qty_ratio_source=qty_ratio_source,
        regime=regime,
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        risk_pct=risk_pct,
        leverage=leverage,
        symbol=symbol,
    )
    contracts = int(math.floor(float(eth_qty) / fv + 1e-12)) if eth_qty > 0 else 0
    if min_qty and contracts > 0 and contracts < int(min_qty):
        meta["error"] = "below_min_qty"
        contracts = 0
    meta["face_value"] = fv
    meta["eth_equivalent"] = round(float(eth_qty or 0), 6)
    meta["final_qty"] = contracts
    meta["add_qty"] = contracts
    if contracts > 0 and price:
        meta["notional_usd"] = round(contracts * fv * float(price), 4)
    return contracts, meta


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
    tv_qty_ratio: float | None = None,
    qty_ratio_source: str = "tv_qty_ratio",
    symbol: str | None = None,
    min_qty: float | None = None,
    risk_pct: float | None = None,
) -> tuple[float, dict]:
    et = str(entry_type or "OPEN").upper()
    if et in ENTRY_TYPES_ADD:
        qr = float(tv_qty_ratio if tv_qty_ratio is not None else regime_add_qty_ratio(regime))
        return compute_vps_add_qty(
            base_qty=base_qty,
            tv_qty_ratio=qr,
            round_fn=round_fn,
            entry_type=et,
            qty_ratio_source=qty_ratio_source,
            regime=regime,
            min_qty=min_qty,
            live_balance=live_balance,
            initial_principal=initial_principal,
            price=price,
            tv_sl=tv_sl,
            risk_pct=risk_pct,
            leverage=exchange_leverage,
            symbol=symbol,
        )
    return compute_vps_open_qty(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        regime=regime,
        leverage=exchange_leverage,
        round_fn=round_fn,
        symbol=symbol,
        min_qty=min_qty,
        risk_pct=risk_pct,
        qty_ratio=float(tv_qty_ratio if tv_qty_ratio is not None else 1.0),
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
    tv_qty_ratio: float | None = None,
    qty_ratio_source: str = "tv_qty_ratio",
    symbol: str | None = None,
    risk_pct: float | None = None,
) -> tuple[int, dict]:
    et = str(entry_type or "OPEN").upper()
    if et in ENTRY_TYPES_ADD:
        qr = float(tv_qty_ratio if tv_qty_ratio is not None else regime_add_qty_ratio(regime))
        return compute_vps_add_contracts(
            base_qty=base_qty,
            tv_qty_ratio=qr,
            entry_type=et,
            qty_ratio_source=qty_ratio_source,
            regime=regime,
            live_balance=live_balance,
            initial_principal=initial_principal,
            price=price,
            tv_sl=tv_sl,
            risk_pct=risk_pct,
            leverage=exchange_leverage,
            face_value=face_value,
            symbol=symbol,
        )
    return compute_vps_open_contracts(
        live_balance=live_balance,
        initial_principal=initial_principal,
        price=price,
        tv_sl=tv_sl,
        regime=regime,
        leverage=exchange_leverage,
        face_value=face_value,
        symbol=symbol,
        risk_pct=risk_pct,
        qty_ratio=float(tv_qty_ratio if tv_qty_ratio is not None else 1.0),
    )
