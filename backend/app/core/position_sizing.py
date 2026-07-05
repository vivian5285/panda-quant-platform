"""Position sizing: cap margin base to initial principal (settlement anchor), not full equity growth."""
from __future__ import annotations


def resolve_sizing_base(live_balance: float, initial_principal: float) -> tuple[float, str]:
    """
    Regime margin% applies to principal cap, not inflated marginBalance after profits.
    Example: principal 700U, regime-4 50% → 350U margin, not 500U when live balance is 1000U.
    """
    live = max(0.0, float(live_balance or 0))
    principal = max(0.0, float(initial_principal or 0))
    if principal > 0:
        return min(principal, live), "principal_cap"
    return live, "live_balance"


def compute_eth_qty(
    *,
    live_balance: float,
    initial_principal: float,
    margin_pct: float,
    leverage: int,
    price: float,
    round_fn,
) -> tuple[float, dict]:
    sizing_base, sizing_source = resolve_sizing_base(live_balance, initial_principal)
    margin_usd = sizing_base * margin_pct
    notional = margin_usd * leverage
    qty = round_fn(notional / price) if price > 0 else 0.0
    return qty, {
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "margin_pct": round(margin_pct, 4),
        "margin_usd": round(margin_usd, 2),
        "notional_usd": round(notional, 2),
        "live_balance": round(live_balance, 2),
        "initial_principal": round(initial_principal, 2),
        "leverage": leverage,
        "price": round(price, 2),
    }


def compute_deepcoin_contracts(
    *,
    live_balance: float,
    initial_principal: float,
    margin_pct: float,
    leverage: int,
    price: float,
    face_value: float,
) -> tuple[int, dict]:
    sizing_base, sizing_source = resolve_sizing_base(live_balance, initial_principal)
    margin_usd = sizing_base * margin_pct
    notional = margin_usd * leverage
    denom = price * face_value
    qty = max(int(notional / denom), 1) if denom > 0 else 1
    return qty, {
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "margin_pct": round(margin_pct, 4),
        "margin_usd": round(margin_usd, 2),
        "notional_usd": round(notional, 2),
        "live_balance": round(live_balance, 2),
        "initial_principal": round(initial_principal, 2),
        "leverage": leverage,
        "price": round(price, 2),
        "face_value": face_value,
    }
