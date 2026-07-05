"""Shared user account stats for member API and admin views."""
import logging
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User, Trade, ApiStatus
from app.schemas import DashboardStats, UserProfile
from app.services.position_snapshot import get_user_live_snapshot
from app.services.principal import fetch_live_equity
from app.services.settlement import get_pending_settlement
from app.services.user_lookup import display_name

logger = logging.getLogger(__name__)


def build_user_profile(user: User) -> UserProfile:
    return UserProfile(
        id=user.id,
        uid=user.uid or "",
        email=user.email,
        phone=user.phone,
        nickname=user.nickname,
        display_name=display_name(user),
        referral_code=user.referral_code or "",
        api_status=user.api_status,
        exchange=user.exchange or "binance",
        api_account_mode=user.api_account_mode or "master",
        exchange_uid=user.exchange_uid,
        master_exchange_uid=user.master_exchange_uid,
        role=user.role,
        is_active=user.is_active,
        high_water_mark=user.high_water_mark,
        has_withdraw_password=bool(user.withdraw_password_hash),
        has_email=bool(user.email),
        has_phone=bool(user.phone),
        initial_principal=float(user.initial_principal or 0),
        initial_principal_at=user.initial_principal_at,
        created_at=user.created_at,
    )


def build_dashboard_stats(db: Session, user: User) -> DashboardStats:
    balance, unrealized, position = 0.0, 0.0, None
    equity = 0.0

    try:
        position, summary = get_user_live_snapshot(db, user)
        if summary:
            equity = float(summary.get("total_margin_balance", 0) or 0)
            balance = float(summary.get("available_balance", equity) or equity)
        if position.get("has_position"):
            unrealized = float(position.get("unrealized_pnl", 0) or 0)
        elif user.api_key_enc and user.api_status == ApiStatus.ACTIVE.value and equity <= 0:
            try:
                equity = fetch_live_equity(user)
                balance = equity
            except Exception:
                pass
    except Exception:
        logger.exception("live snapshot failed user=%s", user.id)
        position = {"has_position": False}

    initial = float(user.initial_principal or 0)
    cycle_pnl = round(equity - initial, 2) if initial > 0 and equity > 0 else 0.0

    trade_cycle_pnl = 0.0
    profit_divergence = 0.0
    try:
        from app.services.profit_audit import sum_closed_trade_pnl, cycle_bounds
        period_start, period_end = cycle_bounds(user)
        trade_cycle_pnl = sum_closed_trade_pnl(db, user.id, period_start, period_end)
        profit_divergence = round(cycle_pnl - trade_cycle_pnl, 2) if initial > 0 else 0.0
    except Exception:
        logger.exception("trade cycle pnl failed user=%s", user.id)

    today = date.today()
    week_start = today - timedelta(days=today.weekday())

    today_pnl = db.query(func.coalesce(func.sum(Trade.realized_pnl), 0)).filter(
        Trade.user_id == user.id, func.date(Trade.closed_at) == today
    ).scalar() or 0

    week_pnl = db.query(func.coalesce(func.sum(Trade.realized_pnl), 0)).filter(
        Trade.user_id == user.id, func.date(Trade.closed_at) >= week_start
    ).scalar() or 0

    total_pnl = db.query(func.coalesce(func.sum(Trade.realized_pnl), 0)).filter(
        Trade.user_id == user.id, Trade.status == "closed"
    ).scalar() or 0

    pending = get_pending_settlement(db, user.id)
    from app.services.trading_control import get_user_control

    ctrl = get_user_control(db, user.id)
    settlement_fee_deferred = bool(ctrl.get("settlement_fee_deferred")) and pending is not None
    pending_out = None
    if pending:
        pending_out = {
            "id": pending.id,
            "user_payable": pending.user_payable,
            "net_profit": pending.net_profit,
            "platform_fee": pending.platform_fee,
            "payment_status": pending.payment_status,
            "period_start": pending.period_start.isoformat(),
            "period_end": pending.period_end.isoformat(),
            "cycle_days": pending.cycle_days or 30,
            "created_at": pending.created_at.isoformat() if pending.created_at else None,
        }

    open_position = position if position.get("has_position") else None

    return DashboardStats(
        balance=balance,
        unrealized_pnl=unrealized,
        today_pnl=float(today_pnl),
        week_pnl=float(week_pnl),
        total_pnl=float(total_pnl),
        initial_principal=initial,
        cycle_pnl=cycle_pnl,
        trade_cycle_pnl=trade_cycle_pnl,
        profit_divergence=profit_divergence,
        initial_principal_at=user.initial_principal_at,
        open_position=open_position,
        settlement_blocked=pending is not None,
        settlement_fee_deferred=settlement_fee_deferred,
        pending_settlement=pending_out,
    )
