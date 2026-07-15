"""Dual profit monitoring: live equity snapshot vs ETHUSDT perpetual trade PnL.

Settlement billing uses closed platform Trade records (historical orders).
Equity snapshots on each supervisor restart detect manual transfers in/out.
Cashflow APIs (Binance/OKX/Gate) refine net-transfer; Deepcoin uses inference.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User, Trade, TradeLog, PrincipalSnapshot
from app.services.principal import fetch_live_equity
from app.services.binance_sync import sync_user_binance_fills
from app.services.alert_service import notify_admin
from app.services.equity_reconcile import (
    build_reconcile_snapshot,
    cycle_start_ms,
    fetch_client_cashflows,
    resolve_user_client,
    summarize_cashflows,
)

logger = logging.getLogger(__name__)
settings = get_settings()


def cycle_bounds(user: User) -> tuple[date, date]:
    end = date.today()
    start = user.settlement_cycle_start or (end - timedelta(days=settings.SETTLEMENT_PRIMARY_DAYS))
    return start, end


def sum_closed_trade_pnl(
    db: Session,
    user_id: int,
    period_start: date | None = None,
    period_end: date | None = None,
) -> float:
    q = db.query(func.coalesce(func.sum(Trade.realized_pnl), 0)).filter(
        Trade.user_id == user_id,
        Trade.status == "closed",
    )
    if period_start is not None:
        q = q.filter(func.date(Trade.closed_at) >= period_start)
    if period_end is not None:
        q = q.filter(func.date(Trade.closed_at) <= period_end)
    return round(float(q.scalar() or 0), 2)


def sum_binance_fill_pnl(
    db: Session,
    user_id: int,
    period_start: date | None = None,
    period_end: date | None = None,
) -> float:
    from app.services.exchange_fill_sync import sum_synced_fill_pnl
    return sum_synced_fill_pnl(db, user_id, period_start, period_end)


def cycle_trade_pnl_authoritative(
    db: Session,
    user: User,
    period_start: date | None = None,
    period_end: date | None = None,
    *,
    sync: bool = True,
) -> tuple[float, dict]:
    """ETH contract realized PnL for billing/admin — exchange fills first."""
    from app.services.exchange_fill_sync import authoritative_eth_cycle_pnl
    return authoritative_eth_cycle_pnl(
        db, user, period_start, period_end, sync=sync,
    )


def _load_cashflow_bundle(user: User, period_start: date | None) -> dict:
    client = resolve_user_client(user)
    rows, source = fetch_client_cashflows(client, start_time_ms=cycle_start_ms(period_start))
    # Deepcoin always returns [] from API — treat as inference path.
    if (user.exchange or "binance").lower() == "deepcoin" and source == "exchange_api" and not rows:
        source = "unsupported"
    summary = summarize_cashflows(rows)
    return {
        "rows": rows,
        "source": source,
        "summary": summary,
    }


def build_dual_profit_report(
    db: Session,
    user: User,
    *,
    live_equity: float | None = None,
    unrealized_pnl: float = 0.0,
) -> dict:
    period_start, period_end = cycle_bounds(user)
    equity = float(live_equity) if live_equity is not None else fetch_live_equity(user)
    initial = float(user.initial_principal or 0)
    trade_cycle, fill_meta = cycle_trade_pnl_authoritative(
        db, user, period_start, period_end, sync=True,
    )
    trade_total, total_meta = cycle_trade_pnl_authoritative(
        db, user, None, None, sync=False,
    )
    fill_cycle = float(fill_meta.get("live_fill_pnl") or fill_meta.get("logged_fill_pnl") or trade_cycle)
    fill_total = float(total_meta.get("live_fill_pnl") or total_meta.get("logged_fill_pnl") or trade_total)
    platform_cycle = float(fill_meta.get("platform_trade_pnl") or sum_closed_trade_pnl(db, user.id, period_start, period_end))

    cash = _load_cashflow_bundle(user, period_start)
    summary = cash["summary"]
    api_transfer = summary["net_transfer"] if cash["source"] == "exchange_api" else None

    reconcile = build_reconcile_snapshot(
        live_equity=equity,
        initial_principal=initial,
        trade_cycle_pnl=trade_cycle,
        trade_pnl_total=trade_total,
        unrealized_pnl=unrealized_pnl,
        exchange_net_transfer=api_transfer,
        exchange_funding=summary["funding"],
        exchange_commission=summary["commission"],
        cashflow_source=cash["source"],
        cashflow_count=summary["count"],
        exchange=user.exchange or "binance",
    )

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "live_equity": reconcile["live_equity"],
        "initial_principal": reconcile["initial_principal"],
        "equity_delta": reconcile["equity_delta"],
        "trade_pnl_cycle": trade_cycle,
        "trade_pnl_total": trade_total,
        "trade_cycle_pnl": trade_cycle,
        "platform_trade_pnl_cycle": platform_cycle,
        "pnl_source": fill_meta.get("source"),
        "pnl_meta": fill_meta,
        "binance_fill_pnl_cycle": fill_cycle,
        "binance_fill_pnl_total": fill_total,
        "divergence_equity_vs_trades": reconcile["profit_divergence"],
        "profit_divergence": reconcile["profit_divergence"],
        "estimated_net_transfer": reconcile["estimated_net_transfer"],
        "transfer_source": reconcile["transfer_source"],
        "transfer_suspected": reconcile["transfer_suspected"],
        "residual": reconcile["residual"],
        "hypotheses": reconcile["hypotheses"],
        "reconcile_note": reconcile["reconcile_note"],
        "suggested_principal": reconcile.get("suggested_principal"),
        "should_rebase_principal": reconcile.get("should_rebase_principal"),
        "cashflow_source": reconcile["cashflow_source"],
        "cashflow_count": reconcile["cashflow_count"],
        "exchange_funding": reconcile["exchange_funding"],
        "exchange_commission": reconcile["exchange_commission"],
        "cycle_pnl": reconcile["cycle_pnl"],
        "symbol": settings.SYMBOL,
        "exchange": user.exchange or "binance",
    }


def settlement_profit_from_trades(
    db: Session,
    user: User,
    period_start: date,
    period_end: date,
) -> tuple[float, dict]:
    """Authoritative settlement profit = ETH contract realized PnL from exchange fills.

    Falls back to platform Trade.realized_pnl only when fills are unavailable.
    Equity / transfers / other-symbol PnL never change the billed amount.
    """
    trade_profit, fill_meta = cycle_trade_pnl_authoritative(
        db, user, period_start, period_end, sync=True,
    )
    fill_profit = float(fill_meta.get("live_fill_pnl") or fill_meta.get("logged_fill_pnl") or trade_profit)
    equity = 0.0
    equity_delta = 0.0
    initial = float(user.initial_principal or 0)
    try:
        equity = fetch_live_equity(user)
        equity_delta = round(equity - initial, 2) if initial > 0 else 0.0
    except Exception:
        pass

    audit = {
        "profit_source": fill_meta.get("source") or "trades",
        "trade_profit": trade_profit,
        "binance_fill_pnl": fill_profit,
        "platform_trade_pnl": fill_meta.get("platform_trade_pnl"),
        "pnl_meta": fill_meta,
        "live_equity": round(equity, 2),
        "initial_principal": round(initial, 2),
        "equity_delta": equity_delta,
        "divergence": round(equity_delta - trade_profit, 2) if initial > 0 else 0.0,
        "fee_basis": "exchange_eth_fill_realized_pnl_hwm",
        "note": "绩效费按交易所 ETH 合约已实现盈亏（高水位）计算；用户划转/他币盈亏不影响应收",
    }
    try:
        from app.services.equity_reconcile import build_reconcile_snapshot

        reconcile = build_reconcile_snapshot(
            live_equity=equity,
            initial_principal=initial,
            trade_cycle_pnl=trade_profit,
            exchange_net_transfer=None,
            cashflow_source="inferred_settlement",
            exchange=user.exchange or "binance",
        )
        audit["estimated_net_transfer"] = reconcile["estimated_net_transfer"]
        audit["transfer_suspected"] = reconcile["transfer_suspected"]
        audit["hypotheses"] = reconcile["hypotheses"]
        audit["suggested_principal"] = reconcile.get("suggested_principal")
    except Exception:
        pass
    return trade_profit, audit


def record_dual_snapshot(
    db: Session,
    user: User,
    report: dict,
    snapshot_type: str = "supervisor_restart",
    note: str = "",
) -> PrincipalSnapshot:
    snap = PrincipalSnapshot(
        user_id=user.id,
        amount=report["live_equity"],
        snapshot_type=snapshot_type,
        note=note or f"{settings.SYMBOL} dual monitor @ restart",
        live_equity=report["live_equity"],
        trade_pnl_cycle=report["trade_pnl_cycle"],
        trade_pnl_total=report["trade_pnl_total"],
        binance_fill_pnl_cycle=report["binance_fill_pnl_cycle"],
        binance_fill_pnl_total=report["binance_fill_pnl_total"],
        equity_delta=report["equity_delta"],
    )
    db.add(snap)
    return snap


def run_startup_dual_audit(db: Session, user: User) -> dict:
    """On supervisor (re)start: sync fills, snapshot equity, reconcile + rebase principal."""
    sync_result = sync_user_binance_fills(db, user, days=180)
    report = build_dual_profit_report(db, user)
    report["binance_sync"] = sync_result

    warn = bool(report.get("transfer_suspected"))
    note = (
        f"cycle_trade_pnl=${report['trade_pnl_cycle']:.2f} "
        f"equity_delta=${report['equity_delta']:.2f} "
        f"net_transfer({report.get('transfer_source')})="
        f"${float(report.get('estimated_net_transfer') or 0):.2f} "
        f"fill_cycle=${report['binance_fill_pnl_cycle']:.4f}"
    )
    if warn:
        hy = ",".join(report.get("hypotheses") or []) or "manual_transfer_suspected"
        note += f" | WARN transfer/divergence | {hy}"

    record_dual_snapshot(db, user, report, snapshot_type="supervisor_restart", note=note)

    rebase_snap = None
    if report.get("should_rebase_principal") or warn:
        from app.services.principal import maybe_rebase_principal_on_divergence

        rebase_snap = maybe_rebase_principal_on_divergence(db, user, report)
        if rebase_snap:
            report["principal_rebased"] = True
            report["principal_after_rebase"] = float(rebase_snap.amount)
            note += f" | REBASE principal→${float(rebase_snap.amount):.2f}"
            # Refresh dual fields after rebase for logging clarity
            report["initial_principal"] = float(rebase_snap.amount)
            report["equity_delta"] = round(
                float(report["live_equity"]) - float(rebase_snap.amount), 2
            )

    from app.services.trade_logger import TradeLogger
    TradeLogger(db).log_event(
        user.id,
        "DUAL_AUDIT",
        (
            f"重启双重监控 · 权益 ${report['live_equity']:.2f} · "
            f"周期交易盈亏 ${report['trade_pnl_cycle']:.2f} · "
            f"划转净额 ${float(report.get('estimated_net_transfer') or 0):.2f}"
            f"({report.get('transfer_source')}) · "
            f"权益变动 ${report['equity_delta']:.2f}"
            + (
                f" · 本金已校正→${float(report.get('principal_after_rebase') or 0):.2f}"
                if rebase_snap else ""
            )
        ),
        report,
    )
    if abs(float(report.get("estimated_net_transfer") or 0)) >= 0.01 or rebase_snap:
        TradeLogger(db).log_event(
            user.id,
            "EQUITY_RECONCILE",
            report.get("reconcile_note") or "equity reconcile",
            {
                "estimated_net_transfer": report.get("estimated_net_transfer"),
                "transfer_source": report.get("transfer_source"),
                "cashflow_source": report.get("cashflow_source"),
                "hypotheses": report.get("hypotheses"),
                "equity_delta": report.get("equity_delta"),
                "trade_cycle_pnl": report.get("trade_pnl_cycle"),
                "exchange": report.get("exchange"),
                "suggested_principal": report.get("suggested_principal"),
                "principal_rebased": bool(rebase_snap),
                "principal_after_rebase": report.get("principal_after_rebase"),
            },
        )
        if rebase_snap:
            TradeLogger(db).log_event(
                user.id,
                "PRINCIPAL_REBASE",
                (
                    f"对账校正初始本金 → ${float(rebase_snap.amount):.2f} "
                    f"（划转/他币盈亏不计入平台操作亏损；绩效费仍按合约交易盈亏结算）"
                ),
                {
                    "amount": float(rebase_snap.amount),
                    "snapshot_id": rebase_snap.id,
                    "hypotheses": report.get("hypotheses"),
                    "trade_cycle_pnl": report.get("trade_pnl_cycle"),
                    "live_equity": report.get("live_equity"),
                },
            )

    db.commit()

    if warn or rebase_snap:
        notify_admin(
            user.id,
            "warning",
            "PROFIT_DIVERGENCE",
            "账户对账：疑似资金划转/他币盈亏" + (" · 本金已校正" if rebase_snap else ""),
            (
                f"合约交易PnL ${report['trade_pnl_cycle']:.2f} · "
                f"权益变动 ${report['equity_delta']:.2f} · "
                f"划转净额 ${float(report.get('estimated_net_transfer') or 0):.2f} "
                f"({report.get('transfer_source')})"
                + (
                    f" · 新本金 ${float(report.get('principal_after_rebase') or 0):.2f}"
                    if rebase_snap else ""
                )
                + " — 结算仍以交易订单为准"
            ),
            report,
        )
        logger.warning(
            "[DualAudit] user=%s exchange=%s trade_cycle=%.2f equity_delta=%.2f "
            "net_transfer=%.2f source=%s rebase=%s hypotheses=%s",
            user.id,
            report.get("exchange"),
            report["trade_pnl_cycle"],
            report["equity_delta"],
            float(report.get("estimated_net_transfer") or 0),
            report.get("transfer_source"),
            bool(rebase_snap),
            report.get("hypotheses"),
        )
    else:
        logger.info(
            "[DualAudit] user=%s equity=%.2f trade_cycle=%.2f net_transfer=%.2f fills_synced=%s",
            user.id,
            report["live_equity"],
            report["trade_pnl_cycle"],
            float(report.get("estimated_net_transfer") or 0),
            sync_result.get("synced", 0),
        )
    return report
