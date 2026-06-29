"""Dual profit monitoring: live equity snapshot vs ETHUSDT perpetual trade PnL.

Settlement billing uses closed platform Trade records (historical orders).
Equity snapshots on each supervisor restart detect manual transfers in/out.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User, Trade, TradeLog, PrincipalSnapshot
from app.services.principal import fetch_live_equity
from app.services.binance_sync import sync_user_binance_fills
from app.services.alert_service import notify_admin

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
    rows = db.query(TradeLog).filter(
        TradeLog.user_id == user_id,
        TradeLog.event_type == "BINANCE_FILL",
    ).all()
    total = 0.0
    for row in rows:
        if not row.detail_json:
            continue
        try:
            detail = json.loads(row.detail_json)
        except json.JSONDecodeError:
            continue
        ts = detail.get("time_ms") or (row.created_at.timestamp() * 1000 if row.created_at else None)
        if ts:
            d = datetime.utcfromtimestamp(ts / 1000).date()
            if period_start and d < period_start:
                continue
            if period_end and d > period_end:
                continue
        total += float(detail.get("realized_pnl", 0))
    return round(total, 4)


def build_dual_profit_report(db: Session, user: User) -> dict:
    period_start, period_end = cycle_bounds(user)
    equity = fetch_live_equity(user)
    initial = float(user.initial_principal or 0)
    trade_cycle = sum_closed_trade_pnl(db, user.id, period_start, period_end)
    trade_total = sum_closed_trade_pnl(db, user.id)
    fill_cycle = sum_binance_fill_pnl(db, user.id, period_start, period_end)
    fill_total = sum_binance_fill_pnl(db, user.id)
    equity_delta = round(equity - initial, 2) if initial > 0 else 0.0
    divergence = round(equity_delta - trade_cycle, 2) if initial > 0 else 0.0

    return {
        "period_start": str(period_start),
        "period_end": str(period_end),
        "live_equity": round(equity, 2),
        "initial_principal": round(initial, 2),
        "equity_delta": equity_delta,
        "trade_pnl_cycle": trade_cycle,
        "trade_pnl_total": trade_total,
        "binance_fill_pnl_cycle": fill_cycle,
        "binance_fill_pnl_total": fill_total,
        "divergence_equity_vs_trades": divergence,
        "symbol": settings.SYMBOL,
    }


def settlement_profit_from_trades(
    db: Session,
    user: User,
    period_start: date,
    period_end: date,
) -> tuple[float, dict]:
    """Authoritative settlement profit = closed platform trades in period."""
    trade_profit = sum_closed_trade_pnl(db, user.id, period_start, period_end)
    fill_profit = sum_binance_fill_pnl(db, user.id, period_start, period_end)
    equity = 0.0
    equity_delta = 0.0
    initial = float(user.initial_principal or 0)
    try:
        equity = fetch_live_equity(user)
        equity_delta = round(equity - initial, 2) if initial > 0 else 0.0
    except Exception:
        pass

    audit = {
        "profit_source": "trades",
        "trade_profit": trade_profit,
        "binance_fill_pnl": fill_profit,
        "live_equity": round(equity, 2),
        "equity_delta": equity_delta,
        "divergence": round(equity_delta - trade_profit, 2) if initial > 0 else 0.0,
    }
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
    """On supervisor (re)start: sync Binance fills, snapshot equity, log trade PnL."""
    sync_result = sync_user_binance_fills(db, user, days=180)
    report = build_dual_profit_report(db, user)
    report["binance_sync"] = sync_result

    divergence = abs(report["divergence_equity_vs_trades"])
    warn = divergence >= settings.PROFIT_DIVERGENCE_WARN_USD and report["initial_principal"] > 0
    note = (
        f"cycle_trade_pnl=${report['trade_pnl_cycle']:.2f} "
        f"equity_delta=${report['equity_delta']:.2f} "
        f"fill_cycle=${report['binance_fill_pnl_cycle']:.4f}"
    )
    if warn:
        note += f" | WARN divergence=${divergence:.2f} (manual transfer suspected)"

    record_dual_snapshot(db, user, report, snapshot_type="supervisor_restart", note=note)

    from app.services.trade_logger import TradeLogger
    TradeLogger(db).log_event(
        user.id,
        "DUAL_AUDIT",
        (
            f"重启双重监控 · 权益 ${report['live_equity']:.2f} · "
            f"周期交易盈亏 ${report['trade_pnl_cycle']:.2f} · "
            f"币安成交盈亏 ${report['binance_fill_pnl_cycle']:.4f} · "
            f"权益变动 ${report['equity_delta']:.2f}"
        ),
        report,
    )

    db.commit()

    if warn:
        notify_admin(
            user.id,
            "warning",
            "PROFIT_DIVERGENCE",
            "权益与交易盈亏偏差较大",
            f"周期交易PnL ${report['trade_pnl_cycle']:.2f} vs 权益变动 ${report['equity_delta']:.2f}，可能有手动划转",
            report,
        )
        logger.warning(
            "[DualAudit] user=%s divergence=%.2f trade_cycle=%.2f equity_delta=%.2f",
            user.id, divergence, report["trade_pnl_cycle"], report["equity_delta"],
        )
    else:
        logger.info(
            "[DualAudit] user=%s equity=%.2f trade_cycle=%.2f fills_synced=%s",
            user.id, report["live_equity"], report["trade_pnl_cycle"], sync_result.get("synced", 0),
        )
    return report
