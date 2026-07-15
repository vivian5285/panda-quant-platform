"""Equity vs trade PnL reconciliation — detect deposits / withdrawals / transfers.

Authoritative cycle profit for billing/UI remains closed-Trade realized PnL.
Equity change (live − principal) mixes trading + transfers + fees; this module
splits those components and reverse-infers net transfers when exchange APIs
cannot list cashflows.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Binance USDT-M income types treated as cash in/out (not trading PnL).
BINANCE_TRANSFER_INCOME_TYPES = frozenset({
    "TRANSFER",
    "INTERNAL_TRANSFER",
    "CROSS_COLLATERAL_TRANSFER",
    "COIN_SWAP_DEPOSIT",
    "COIN_SWAP_WITHDRAW",
    "WELCOME_BONUS",
    "REFERRAL_KICKBACK",
    "API_REBATE",
    "COMMISSION_REBATE",
    "CONTEST_REWARD",
})

# Residual "other" fees often mistaken for losses when equity-only is shown.
BINANCE_FEE_INCOME_TYPES = frozenset({
    "COMMISSION",
    "FUNDING_FEE",
    "INSURANCE_CLEAR",
    "OPTIONS_PREMIUM_FEE",
    "POSITION_LIMIT_INCREASE_FEE",
})

# OKX account bill type codes that are transfers / balance adjustments.
OKX_TRANSFER_BILL_TYPES = frozenset({
    "1",   # Transfer
    "6",   # Margin transfer
    "11",  # System token conversion
    "26",  # Structured products transfer
    "160", # Manual transfer
    "173", # From copy trading
    "174", # To copy trading
    "184", # Conversion
})


def compute_rebased_principal(
    live_equity: float,
    trade_cycle_pnl: float,
    unrealized_pnl: float = 0.0,
) -> float:
    """New baseline so equity − principal ≈ platform contract cycle PnL (+ UPL)."""
    equity = float(live_equity or 0)
    if equity <= 0:
        return 0.0
    return round(max(0.0, equity - float(trade_cycle_pnl or 0) - float(unrealized_pnl or 0)), 2)


def enrich_hypotheses_for_residual(
    hypotheses: list[str],
    *,
    residual: float,
    net_transfer: float,
    transfer_source: str,
    warn_usd: float,
) -> list[str]:
    out = list(hypotheses or [])
    if abs(residual) >= warn_usd and transfer_source == "exchange_api":
        if "likely_other_symbol_or_external_pnl" not in out:
            out.append("likely_other_symbol_or_external_pnl")
    if abs(net_transfer) >= warn_usd and abs(residual) < warn_usd:
        if "cashflow_explains_equity_gap" not in out:
            out.append("cashflow_explains_equity_gap")
    return out


def cycle_start_ms(period_start: date | None) -> int | None:
    if not period_start:
        return None
    dt = datetime(period_start.year, period_start.month, period_start.day, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def divergence_warn_threshold(initial_principal: float) -> float:
    """Warn when |residual/transfer| exceeds flat USD or 5% of principal (min $10)."""
    flat = float(getattr(settings, "PROFIT_DIVERGENCE_WARN_USD", 10) or 10)
    principal = float(initial_principal or 0)
    pct = round(principal * 0.05, 2) if principal > 0 else 0.0
    return max(flat, pct, 10.0)


def build_reconcile_snapshot(
    *,
    live_equity: float,
    initial_principal: float,
    trade_cycle_pnl: float,
    trade_pnl_total: float = 0.0,
    unrealized_pnl: float = 0.0,
    exchange_net_transfer: float | None = None,
    exchange_funding: float = 0.0,
    exchange_commission: float = 0.0,
    cashflow_source: str = "unavailable",
    cashflow_count: int = 0,
    exchange: str | None = None,
) -> dict[str, Any]:
    """Compute equity_delta, estimated transfers, residual, and human hypotheses."""
    equity = float(live_equity or 0)
    initial = float(initial_principal or 0)
    trade_cycle = round(float(trade_cycle_pnl or 0), 2)
    trade_total = round(float(trade_pnl_total or 0), 2)
    upl = round(float(unrealized_pnl or 0), 2)
    funding = round(float(exchange_funding or 0), 4)
    commission = round(float(exchange_commission or 0), 4)

    equity_delta = round(equity - initial, 2) if initial > 0 and equity > 0 else 0.0
    # Equity change ≈ trade_cycle + UPL + transfers + funding + commission + residual
    trading_explained = round(trade_cycle + upl + funding + commission, 2)

    if exchange_net_transfer is not None:
        net_transfer = round(float(exchange_net_transfer), 2)
        transfer_source = cashflow_source or "exchange_api"
        residual = round(equity_delta - trading_explained - net_transfer, 2) if initial > 0 else 0.0
    else:
        # Reverse-infer: unexplained equity move attributed to net transfer.
        net_transfer = round(equity_delta - trading_explained, 2) if initial > 0 else 0.0
        transfer_source = "inferred"
        residual = 0.0

    # Legacy-compatible divergence: equity_delta − trade_cycle (ignores transfer API).
    profit_divergence = round(equity_delta - trade_cycle, 2) if initial > 0 else 0.0
    warn_usd = divergence_warn_threshold(initial)
    abs_signal = max(abs(net_transfer), abs(residual), abs(profit_divergence - (net_transfer if transfer_source == "inferred" else 0)))
    # Prefer residual when we have API transfers; else |inferred transfer|.
    signal = abs(residual) if transfer_source == "exchange_api" else abs(net_transfer)
    transfer_suspected = bool(initial > 0 and signal >= warn_usd)

    hypotheses: list[str] = []
    if transfer_suspected:
        if net_transfer < -1e-9:
            hypotheses.append("likely_manual_withdraw_or_transfer_out")
        elif net_transfer > 1e-9:
            hypotheses.append("likely_manual_deposit_or_transfer_in")
        if abs(residual) >= warn_usd and transfer_source == "exchange_api":
            hypotheses.append("unexplained_residual_after_known_transfers")
        if abs(trade_cycle) < abs(equity_delta) * 0.2 and abs(equity_delta) >= warn_usd:
            hypotheses.append("equity_move_dominated_by_non_trade_cashflow")
    if cashflow_source in ("unavailable", "error", "unsupported") and abs(profit_divergence) >= warn_usd:
        hypotheses.append("exchange_cashflow_api_unavailable_use_inference")

    hypotheses = enrich_hypotheses_for_residual(
        hypotheses,
        residual=residual,
        net_transfer=net_transfer,
        transfer_source=transfer_source,
        warn_usd=warn_usd,
    )

    # Suggested new principal to re-align monitoring (does not affect settlement trade PnL).
    suggested_principal = compute_rebased_principal(equity, trade_cycle, upl)
    should_rebase = bool(
        transfer_suspected
        and suggested_principal > 0
        and abs(suggested_principal - initial) >= warn_usd
    )

    note_parts = [
        f"本金 ${initial:.2f}",
        f"权益 ${equity:.2f}",
        f"权益变动 ${equity_delta:.2f}",
        f"合约交易盈亏 ${trade_cycle:.2f}",
    ]
    if upl:
        note_parts.append(f"浮盈 ${upl:.2f}")
    note_parts.append(f"划转净额({transfer_source}) ${net_transfer:.2f}")
    if funding:
        note_parts.append(f"资金费 ${funding:.4f}")
    if commission:
        note_parts.append(f"手续费 ${commission:.4f}")
    if residual:
        note_parts.append(f"残差 ${residual:.2f}")
    if should_rebase:
        note_parts.append(f"建议校正本金 ${suggested_principal:.2f}")
    if hypotheses:
        note_parts.append("推断: " + ",".join(hypotheses))

    return {
        "exchange": exchange,
        "live_equity": round(equity, 2),
        "initial_principal": round(initial, 2),
        "equity_delta": equity_delta,
        "trade_cycle_pnl": trade_cycle,
        "trade_pnl_total": trade_total,
        "unrealized_pnl": upl,
        "estimated_net_transfer": net_transfer,
        "transfer_source": transfer_source,
        "cashflow_source": cashflow_source,
        "cashflow_count": int(cashflow_count or 0),
        "exchange_funding": funding,
        "exchange_commission": commission,
        "residual": residual,
        "profit_divergence": profit_divergence,
        "transfer_suspected": transfer_suspected,
        "divergence_warn_usd": warn_usd,
        "hypotheses": hypotheses,
        "suggested_principal": suggested_principal,
        "should_rebase_principal": should_rebase,
        "reconcile_note": " · ".join(note_parts),
        # Admin primary cycle metric = true contract PnL (not equity change).
        "cycle_pnl": trade_cycle,
    }


def summarize_cashflows(rows: list[dict]) -> dict[str, Any]:
    net_transfer = 0.0
    funding = 0.0
    commission = 0.0
    realized = 0.0
    other = 0.0
    for row in rows or []:
        amt = float(row.get("amount") or 0)
        kind = str(row.get("kind") or "other").lower()
        if kind == "transfer":
            net_transfer += amt
        elif kind == "funding":
            funding += amt
        elif kind == "commission":
            commission += amt
        elif kind == "realized_pnl":
            realized += amt
        else:
            other += amt
    return {
        "net_transfer": round(net_transfer, 2),
        "funding": round(funding, 4),
        "commission": round(commission, 4),
        "realized_pnl": round(realized, 4),
        "other": round(other, 4),
        "count": len(rows or []),
    }


def fetch_client_cashflows(client: Any, start_time_ms: int | None = None) -> tuple[list[dict], str]:
    """Call exchange client.get_futures_cashflows; return (rows, source_tag)."""
    if client is None:
        return [], "unavailable"
    fn = getattr(client, "get_futures_cashflows", None)
    if not callable(fn):
        return [], "unsupported"
    try:
        rows = fn(start_time_ms=start_time_ms) or []
        if not isinstance(rows, list):
            return [], "error"
        return rows, "exchange_api"
    except Exception as exc:
        logger.warning(
            "[EquityReconcile] cashflow fetch failed exchange=%s user=%s: %s",
            getattr(client, "exchange_id", "?"),
            getattr(client, "user_id", "?"),
            exc,
        )
        return [], "error"


def resolve_user_client(user) -> Any | None:
    """Best-effort live client from supervisor pool, else decrypt + factory."""
    try:
        from app.services.dispatcher import supervisor_pool
        from app.utils.crypto import decrypt_text
        from app.core.exchange_factory import create_exchange_client

        supervisor = supervisor_pool.get(user.id)
        if supervisor and getattr(supervisor, "client", None):
            return supervisor.client
        if user.api_key_enc and user.api_secret_enc:
            passphrase = decrypt_text(user.passphrase_enc) if user.passphrase_enc else ""
            return create_exchange_client(
                user,
                decrypt_text(user.api_key_enc),
                decrypt_text(user.api_secret_enc),
                passphrase,
            )
    except Exception as exc:
        logger.warning("[EquityReconcile] resolve client failed user=%s: %s", getattr(user, "id", None), exc)
    return None
