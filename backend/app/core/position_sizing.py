"""Position sizing helpers — equity read + legacy margin helpers (tests only).

Live OPEN/ADD sizing is TV-only via ``tv_entry_sizing.py``
(risk_pct / qty_ratio / leverage). Do not use ``compute_eth_qty`` /
``compute_deepcoin_contracts`` for live entry.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def read_contract_equity(client) -> float:
    """Total U-margined futures equity — not available margin locked in positions."""
    if hasattr(client, "get_futures_account_summary"):
        try:
            summary = client.get_futures_account_summary() or {}
            for key in ("total_margin_balance", "margin_balance", "total_wallet_balance"):
                val = float(summary.get(key, 0) or 0)
                if val > 0:
                    return val
        except Exception as e:
            logger.debug("read_contract_equity summary failed: %s", e)
    if hasattr(client, "get_available_balance"):
        return float(client.get_available_balance() or 0)
    return 0.0


def resolve_principal_sizing_base(equity_balance: float, initial_principal: float) -> tuple[float, str]:
    """
    Sizing anchor for both open orders and cap alignment.

    When ``initial_principal`` is set (normal path), always use it — not available margin,
    not inflated post-profit equity. Floor to equity only after drawdown below principal.
    """
    equity = max(0.0, float(equity_balance or 0))
    principal = max(0.0, float(initial_principal or 0))
    if principal > 0:
        if equity > 0 and equity < principal:
            return equity, "principal_cap_equity_floor"
        return principal, "principal_cap"
    return equity, "equity_balance"


def resolve_sizing_base(live_balance: float, initial_principal: float) -> tuple[float, str]:
    """Alias — ``live_balance`` must be total contract equity, not available margin."""
    return resolve_principal_sizing_base(live_balance, initial_principal)


def resolve_cap_sizing_base(equity_balance: float, initial_principal: float) -> tuple[float, str]:
    """Alias for cap guard — same principal anchor as open orders."""
    return resolve_principal_sizing_base(equity_balance, initial_principal)

def compute_eth_qty(
    *,
    live_balance: float,
    initial_principal: float,
    margin_pct: float,
    leverage: int,
    price: float,
    round_fn,
) -> tuple[float, dict]:
    sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)
    margin_usd = sizing_base * margin_pct
    notional = margin_usd * leverage
    qty = round_fn(notional / price) if price > 0 else 0.0
    return qty, {
        "sizing_base": round(sizing_base, 2),
        "sizing_source": sizing_source,
        "margin_pct": round(margin_pct, 4),
        "margin_usd": round(margin_usd, 2),
        "notional_usd": round(notional, 2),
        "equity_balance": round(live_balance, 2),
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
    sizing_base, sizing_source = resolve_principal_sizing_base(live_balance, initial_principal)
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
        "equity_balance": round(live_balance, 2),
        "initial_principal": round(initial_principal, 2),
        "leverage": leverage,
        "price": round(price, 2),
        "face_value": face_value,
    }
