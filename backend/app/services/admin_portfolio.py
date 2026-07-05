"""Admin portfolio snapshots for API-managed users."""
from __future__ import annotations

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ApiStatus, Trade, User
from app.services.admin_user_stats import user_cumulative_pnl
from app.services.dispatcher import supervisor_pool
from app.services.position_snapshot import (
    ensure_open_trade_from_snapshot,
    get_supervisor_account_summary,
    get_supervisor_position_status,
    position_fields_from_status,
)
from app.services.query_filters import apply_trade_date_filter, parse_date_param
from app.services.trading_control import get_user_control
from app.services.user_account import build_dashboard_stats

logger = logging.getLogger(__name__)


def _open_position_dict(dash) -> dict:
    pos = getattr(dash, "open_position", None)
    if isinstance(pos, dict):
        return pos
    if pos is None:
        return {}
    if hasattr(pos, "model_dump"):
        return pos.model_dump()
    return dict(pos) if pos else {}


def build_managed_account_row(db: Session, user: User) -> dict:
    snapshot_error: str | None = None
    try:
        dash = build_dashboard_stats(db, user)
        pos = _open_position_dict(dash)
        ctrl = get_user_control(db, user.id)
        cumulative = user_cumulative_pnl(db, user.id)

        # Prefer live supervisor snapshot when pool is active (all exchanges).
        supervisor = supervisor_pool.get(user.id)
        if supervisor:
            live_pos = get_supervisor_position_status(supervisor, db=db, user_id=user.id)
            summary = get_supervisor_account_summary(supervisor, user=user, position=live_pos)
            if summary:
                equity = float(summary.get("total_margin_balance", 0) or 0)
                balance = float(summary.get("available_balance", equity) or equity)
                dash.balance = balance
                if equity > 0 and float(user.initial_principal or 0) > 0:
                    dash.cycle_pnl = round(equity - float(user.initial_principal), 2)
            if live_pos.get("has_position"):
                ensure_open_trade_from_snapshot(db, user.id, supervisor, live_pos)
                pos = live_pos
                dash.unrealized_pnl = float(live_pos.get("unrealized_pnl", 0) or 0)
                dash.open_position = live_pos
            elif live_pos.get("error") and not live_pos.get("api_degraded"):
                snapshot_error = str(live_pos["error"])
            elif live_pos.get("api_degraded"):
                snapshot_error = None

        trade_count = db.query(Trade).filter(Trade.user_id == user.id).count()
        closed_count = db.query(Trade).filter(
            Trade.user_id == user.id,
            Trade.status == "closed",
        ).count()

        pf = position_fields_from_status(pos)

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
            "balance": float(dash.balance or 0),
            "unrealized_pnl": float(dash.unrealized_pnl or pf["position_unrealized"] or 0),
            "cycle_pnl": float(dash.cycle_pnl or 0),
            "initial_principal": float(dash.initial_principal or 0),
            "today_pnl": float(dash.today_pnl or 0),
            "week_pnl": float(dash.week_pnl or 0),
            "total_pnl": float(dash.total_pnl or 0),
            "cumulative_trade_pnl": cumulative,
            "trade_count": trade_count,
            "closed_trade_count": closed_count,
            "snapshot_error": snapshot_error,
            "snapshot_source": pf.get("snapshot_source"),
            "snapshot_degraded": pf.get("snapshot_degraded", False),
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
    errors = sum(1 for r in rows if r.get("snapshot_error"))
    return {
        "account_count": len(rows),
        "with_position": sum(1 for r in rows if r.get("has_position")),
        "total_balance": round(sum(float(r.get("balance") or 0) for r in rows), 2),
        "total_unrealized": round(sum(float(r.get("unrealized_pnl") or 0) for r in rows), 2),
        "total_cumulative_pnl": round(sum(float(r.get("cumulative_trade_pnl") or 0) for r in rows), 2),
        "snapshot_errors": errors,
    }
