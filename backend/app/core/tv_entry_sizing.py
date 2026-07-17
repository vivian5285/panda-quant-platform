"""VPS entry sizing — OPEN: VPS risk formula; ADD: base_qty × TV qty_ratio (regime dynamic)."""

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
    """档位系数 — legacy OPEN path (VPS_RISK_PCT × scale)."""
    r = clamp_regime(int(regime or 3))
    return {
        1: float(settings.REGIME_SCALE_1),
        2: float(settings.REGIME_SCALE_2),
        3: float(settings.REGIME_SCALE_3),
        4: float(settings.REGIME_SCALE_4),
    }.get(r, 1.0)


def regime_margin_coeff(regime: int) -> float:
    """Dual-symbol OPEN: margin = equity × this coeff (R1 8% / R2 14% / R3 20% / R4 26%)."""
    r = clamp_regime(int(regime or 3))
    return {
        1: float(getattr(settings, "REGIME_MARGIN_1", 0.08) or 0.08),
        2: float(getattr(settings, "REGIME_MARGIN_2", 0.14) or 0.14),
        3: float(getattr(settings, "REGIME_MARGIN_3", 0.20) or 0.20),
        4: float(getattr(settings, "REGIME_MARGIN_4", 0.26) or 0.26),
    }.get(r, float(getattr(settings, "REGIME_MARGIN_3", 0.20) or 0.20))


def regime_add_qty_ratio(regime: int) -> float:
    """Pine v6.9.93 动态加仓默认比例 — TV 未传 qty_ratio 时的回退."""
    r = clamp_regime(int(regime or 3))
    return {
        1: float(getattr(settings, "ADD_RATIO_REG1", 0.0) or 0.0),
        2: float(getattr(settings, "ADD_RATIO_REG2", 0.3) or 0.3),
        3: float(getattr(settings, "ADD_RATIO_REG3", 0.5) or 0.5),
        4: float(getattr(settings, "ADD_RATIO_REG4", 0.7) or 0.7),
    }.get(r, float(settings.ADD_QTY_RATIO or 0.5))


def max_add_times_for_regime(regime: int) -> int:
    """Pine v6.9.93 各档位最大加仓次数."""
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
    """
    ADD 专用：优先 TV qty_ratio；缺失时按档位默认（对齐 Pine 动态加仓）。
    OPEN 不应调用此函数。
    """
    raw = _parse_float((data or {}).get("qty_ratio"))
    if raw is not None:
        return max(raw, 0.0), "tv_qty_ratio"
    return regime_add_qty_ratio(regime), "regime_default"


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


def parse_tv_entry_fields(payload: dict | None) -> dict[str, Any]:
    data = dict(payload or {})
    entry_type = str(data.get("entry_type") or "OPEN").upper().strip()
    if entry_type not in ENTRY_TYPES:
        entry_type = "OPEN"
    regime = _parse_regime(data.get("regime"))
    fields: dict[str, Any] = {
        "entry_type": entry_type,
        "regime": regime,
        "uses_vps_sizing": True,
        "tv_qty_ratio_ignored": entry_type == "OPEN",
    }
    if entry_type in ENTRY_TYPES_ADD:
        r = regime if regime is not None else 3
        qty_ratio, ratio_source = resolve_tv_add_qty_ratio(data, r)
        fields["qty_ratio"] = round(qty_ratio, 4)
        fields["add_qty_ratio"] = round(qty_ratio, 4)
        fields["qty_ratio_source"] = ratio_source
        fields["max_add_times"] = max_add_times_for_regime(r)
    return fields


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
    symbol: str | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    OPEN (dual-symbol spec):
      margin = TOTAL_EQUITY × regime_margin_coeff
      notional = margin × leverage (25×)
      qty = notional / price
    tv_sl 不参与张数；硬止损由 vps_hard_sl 按入场价×档位% 计算。
    """
    from app.core.symbol_precision import min_qty_for
    from app.core.symbol_registry import normalize_canonical_symbol

    sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)
    # Checklist: OPEN uses realtime TOTAL_EQUITY (total margin balance), not availableBalance
    if float(live_balance or 0) > 0:
        sizing_base = float(live_balance)
        sizing_source = "total_equity"
    lev = max(int(leverage or 1), 1)
    price_f = float(price or 0)
    tv_sl_f = float(tv_sl or 0)
    r = clamp_regime(int(regime or 3))
    margin_coeff = regime_margin_coeff(r)
    can = normalize_canonical_symbol(symbol)
    meta: dict[str, Any] = {
        "sizing_mode": "vps_open_margin_coeff",
        "entry_type": "OPEN",
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "leverage": lev,
        "price": round(price_f, 2),
        "tv_sl": round(tv_sl_f, 2),
        "equity_balance": round(live_balance, 2),
        "initial_principal": round(initial_principal, 2),
        "regime": r,
        "margin_coeff": round(margin_coeff, 4),
        "symbol": can,
    }
    if price_f <= 0:
        meta["error"] = "invalid_price"
        return 0.0, meta

    margin_usd = sizing_base * margin_coeff
    position_value = margin_usd * lev
    raw_qty = position_value / price_f
    meta["margin_usd"] = round(margin_usd, 4)
    meta["position_value"] = round(position_value, 4)
    meta["order_amount"] = round(position_value, 4)
    meta["notional_usd"] = round(position_value, 4)
    if tv_sl_f > 0:
        meta["sl_distance"] = round(abs(price_f - tv_sl_f), 4)

    default_min = min_qty_for(can) if can else float(settings.MIN_ORDER_QTY_ETH)
    mn = float(min_qty if min_qty is not None else default_min)
    mx = float(max_qty if max_qty is not None else settings.MAX_POSITION_QTY)
    qty = round_fn(_clamp_qty(raw_qty, min_qty=mn, max_qty=mx))
    meta["raw_qty"] = round(raw_qty, 6)
    meta["base_qty"] = qty
    meta["final_qty"] = qty
    return qty, meta


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
) -> tuple[float, dict[str, Any]]:
    """PYRAMID / PROFIT_ADD: add_qty = base_qty × TV qty_ratio（首仓基准 × 策略动态系数）."""
    bq = max(float(base_qty or 0), 0.0)
    qr = max(float(tv_qty_ratio or 0), 0.0)
    raw = bq * qr
    mn = float(min_qty if min_qty is not None else settings.MIN_ORDER_QTY_ETH)
    mx = float(max_qty if max_qty is not None else settings.MAX_POSITION_QTY)
    qty = round_fn(_clamp_qty(raw, min_qty=mn, max_qty=mx)) if qr > 0 else 0.0
    meta = {
        "sizing_mode": "vps_add",
        "entry_type": entry_type,
        "base_qty": round(bq, 6),
        "add_qty_ratio": round(qr, 4),
        "qty_ratio": round(qr, 4),
        "qty_ratio_source": qty_ratio_source,
        "add_qty": qty,
        "final_qty": qty,
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
        symbol=symbol,
    )
    if meta.get("order_amount"):
        meta["notional_usd"] = round(meta["order_amount"], 4)
    meta["face_value"] = face_value
    return int(qty), meta


def compute_vps_add_contracts(
    *,
    base_qty: float,
    tv_qty_ratio: float,
    entry_type: str = "PYRAMID",
    min_qty: float | None = None,
    max_qty: float | None = None,
    qty_ratio_source: str = "tv_qty_ratio",
    regime: int | None = None,
) -> tuple[int, dict[str, Any]]:
    def _round_contracts(x: float) -> float:
        return max(int(x), 1)

    qty, meta = compute_vps_add_qty(
        base_qty=base_qty,
        tv_qty_ratio=tv_qty_ratio,
        round_fn=_round_contracts,
        min_qty=min_qty or 1,
        max_qty=max_qty,
        entry_type=entry_type,
        qty_ratio_source=qty_ratio_source,
        regime=regime,
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
    tv_qty_ratio: float | None = None,
    qty_ratio_source: str = "tv_qty_ratio",
    symbol: str | None = None,
    min_qty: float | None = None,
) -> tuple[float, dict]:
    if entry_type in ENTRY_TYPES_ADD:
        if base_qty <= 0:
            return 0.0, {"error": "missing_base_qty", "entry_type": entry_type}
        qr = float(tv_qty_ratio if tv_qty_ratio is not None else regime_add_qty_ratio(regime))
        return compute_vps_add_qty(
            base_qty=base_qty,
            tv_qty_ratio=qr,
            round_fn=round_fn,
            entry_type=entry_type,
            qty_ratio_source=qty_ratio_source,
            regime=regime,
            min_qty=min_qty,
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
) -> tuple[int, dict]:
    if entry_type in ENTRY_TYPES_ADD:
        if base_qty <= 0:
            return 0, {"error": "missing_base_qty", "entry_type": entry_type}
        qr = float(tv_qty_ratio if tv_qty_ratio is not None else regime_add_qty_ratio(regime))
        return compute_vps_add_contracts(
            base_qty=base_qty,
            tv_qty_ratio=qr,
            entry_type=entry_type,
            qty_ratio_source=qty_ratio_source,
            regime=regime,
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
    )
