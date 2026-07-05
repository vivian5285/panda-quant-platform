"""Admin portfolio snapshots for API-managed users."""
from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ApiStatus, Trade, User
from app.services.admin_user_stats import user_cumulative_pnl
from app.services.dispatcher import supervisor_pool
from app.services.position_snapshot import (
    get_user_live_snapshot,
    position_fields_from_status,
)
from app.services.query_filters import apply_trade_date_filter, parse_date_param
from app.services.trading_control import get_user_control

logger = logging.getLogger(__name__)


def build_managed_account_row(db: Session, user: User) -> dict:
    snapshot_error: str | None = None
    try:
        ctrl = get_user_control(db, user.id)
        cumulative = user_cumulative_pnl(db, user.id)
        supervisor = supervisor_pool.get(user.id)

        position, summary = get_user_live_snapshot(db, user)
        pf = position_fields_from_status(position)

        balance = float(summary.get("available_balance", 0) or 0)
        equity = float(summary.get("total_margin_balance", 0) or 0)
        unrealized = float(position.get("unrealized_pnl", 0) or pf["position_unrealized"] or 0)
        initial = float(user.initial_principal or 0)
        cycle_pnl = round(equity - initial, 2) if initial > 0 and equity > 0 else 0.0

        if position.get("error") and not position.get("has_position") and not position.get("api_degraded"):
            snapshot_error = str(position["error"])
        elif position.get("api_degraded") or summary.get("api_degraded"):
            snapshot_error = None

        trade_count = db.query(Trade).filter(Trade.user_id == user.id).count()
        closed_count = db.query(Trade).filter(
            Trade.user_id == user.id,
            Trade.status == "closed",
        ).count()

        return {
            "user_id": user.id,
            "uid": user.uid or "",
            "email": user.email,
            "phone": user.phone,
            "nickname": user.nickname,
            "exchange": user.exchange or "binance",
            "api_status": user.api_status or ApiStatus.NONE.value,
            "is_active": bool(user.is_active),
            "supervisor_active": supervisor is not None,
            "trading_paused": bool(ctrl.get("trading_paused")),
            "balance": balance,
            "unrealized_pnl": unrealized,
            "cycle_pnl": cycle_pnl,
            "initial_principal": initial,
            "today_pnl": 0.0,
            "week_pnl": 0.0,
            "total_pnl": float(
                db.query(func.coalesce(func.sum(Trade.realized_pnl), 0))
                .filter(Trade.user_id == user.id, Trade.status == "closed")
                .scalar() or 0
            ),
            "cumulative_trade_pnl": cumulative,
            "trade_count": trade_count,
            "closed_trade_count": closed_count,
            "snapshot_error": snapshot_error,
            "snapshot_source": pf.get("snapshot_source"),
            "snapshot_degraded": pf.get("snapshot_degraded", False) or bool(summary.get("api_degraded")),
            **{k: v for k, v in pf.items() if k not in ("snapshot_source", "snapshot_degraded")},
        }
    except Exception as e:
        logger.exception("build_managed_account_row failed user=%s", user.id)
        ctrl = get_user_control(db, user.id)
        return {
            "user_id": user.id,
            "uid": user.uid or "",
            "email": user.email,
            "phone": user.phone,
            "nickname": user.nickname,
            "exchange": user.exchange or "binance",
            "api_status": user.api_status or ApiStatus.NONE.value,
            "is_active": bool(user.is_active),
            "supervisor_active": supervisor_pool.get(user.id) is not None,
            "trading_paused": bool(ctrl.get("trading_paused")),
            "balance": 0.0,
            "unrealized_pnl": 0.0,
            "cycle_pnl": 0.0,
            "initial_principal": float(user.initial_principal or 0),
            "today_pnl": 0.0,
            "week_pnl": 0.0,
            "total_pnl": 0.0,
            "cumulative_trade_pnl": user_cumulative_pnl(db, user.id),
            "has_position": False,
            "position_side": None,
            "position_qty": 0.0,
            "position_entry": 0.0,
            "position_mark": 0.0,
            "position_unrealized": 0.0,
            "trade_count": 0,
            "closed_trade_count": 0,
            "snapshot_error": str(e),
            "snapshot_degraded": False,
            "snapshot_source": None,
        }


def list_managed_accounts(
    db: Session,
    *,
    api_status: str | None = None,
    has_position: bool | None = None,
) -> list[dict]:
    q = db.query(User).filter(User.api_key_enc.isnot(None))
    if api_status:
        q = q.filter(User.api_status == api_status)
    else:
        q = q.filter(User.api_status == ApiStatus.ACTIVE.value)
    users = q.order_by(User.id.asc()).all()
    rows = [build_managed_account_row(db, u) for u in users]
    if has_position is True:
        rows = [r for r in rows if r["has_position"]]
    elif has_position is False:
        rows = [r for r in rows if not r["has_position"]]
    return rows


def user_trade_stats(
    db: Session,
    user_id: int,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    q = db.query(Trade).filter(Trade.user_id == user_id, Trade.status == "closed")
    q = apply_trade_date_filter(q, parse_date_param(start), parse_date_param(end), Trade)
    trades = q.order_by(Trade.closed_at.desc()).all()
    pnls = [float(t.realized_pnl or 0) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    total = round(sum(pnls), 4)
    funding = round(sum(float(t.funding_fee or 0) for t in trades), 4)
    return {
        "trade_count": len(trades),
        "win_count": wins,
        "loss_count": losses,
        "win_rate": round(wins / len(trades) * 100, 1) if trades else 0.0,
        "realized_pnl": total,
        "funding_fee": funding,
        "avg_pnl": round(total / len(trades), 4) if trades else 0.0,
    }


def portfolio_summary(rows: list[dict]) -> dict:
    errors = sum(1 for r in rows if r.get("snapshot_error") and not r.get("has_position"))
    return {
        "account_count": len(rows),
        "with_position": sum(1 for r in rows if r.get("has_position")),
        "total_balance": round(sum(float(r.get("balance") or 0) for r in rows), 2),
        "total_unrealized": round(sum(float(r.get("unrealized_pnl") or 0) for r in rows), 2),
        "total_cumulative_pnl": round(sum(float(r.get("cumulative_trade_pnl") or 0) for r in rows), 2),
        "snapshot_errors": errors,
    }
