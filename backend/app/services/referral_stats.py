"""Referral downline financial snapshot for promoters."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import User, Trade, PaymentStatus, ApiStatus
from app.services.dispatcher import supervisor_pool
from app.services.position_snapshot import (
    get_supervisor_account_summary,
    get_supervisor_position_status,
    position_fields_from_status,
)
from app.services.principal import fetch_live_equity
from app.services.settlement import get_pending_settlement, user_has_open_position
from app.services.user_lookup import display_name

settings = get_settings()


def _mask_identity(user: User) -> str:
    if user.email:
        parts = user.email.split("@")
        return parts[0][:3] + "***@" + parts[1] if len(parts) == 2 else user.email
    if user.phone:
        return user.phone[:3] + "****" + user.phone[-4:] if len(user.phone) >= 7 else "****"
    return f"UID:{user.uid}"


def build_downline_stats(db: Session, user: User) -> dict:
    initial = float(user.initial_principal or 0)
    equity = 0.0
    balance = 0.0
    unrealized = 0.0
    has_position = False
    position_side = None
    position_qty = 0.0
    position_entry = 0.0
    position_mark = 0.0

    supervisor = supervisor_pool.get(user.id)
    if supervisor:
        try:
            summary = get_supervisor_account_summary(supervisor)
            equity = float(summary.get("total_margin_balance", 0) or 0)
            balance = float(summary.get("available_balance", equity) or equity)
            status = get_supervisor_position_status(supervisor)
            pf = position_fields_from_status(status)
            has_position = pf["has_position"]
            position_side = pf["position_side"]
            position_qty = pf["position_qty"]
            position_entry = pf["position_entry"]
            position_mark = pf["position_mark"]
            unrealized = pf["position_unrealized"] if has_position else 0.0
        except Exception:
            pass
    elif user.api_key_enc and user.api_status == ApiStatus.ACTIVE.value:
        try:
            equity = fetch_live_equity(user)
            balance = equity
        except Exception:
            pass

    if not has_position:
        has_position = user_has_open_position(db, user.id)

    cycle_pnl = round(equity - initial, 2) if initial > 0 and equity > 0 else 0.0
    total_pnl = db.query(func.coalesce(func.sum(Trade.realized_pnl), 0)).filter(
        Trade.user_id == user.id, Trade.status == "closed"
    ).scalar() or 0

    pending = get_pending_settlement(db, user.id)
    settlement_status = pending.payment_status if pending else "none"
    pending_perf_fee = 0.0
    pending_net_profit = 0.0
    settlement_period = None
    settlement_id = None
    if pending and pending.payment_status in (
        PaymentStatus.PENDING.value,
        PaymentStatus.PAID.value,
    ):
        pending_perf_fee = round(float(pending.user_payable or 0), 2)
        pending_net_profit = round(float(pending.net_profit or 0), 2)
        settlement_id = pending.id
        settlement_period = f"{pending.period_start} ~ {pending.period_end}"

    return {
        "id": user.id,
        "uid": user.uid or "",
        "email": _mask_identity(user),
        "display_name": display_name(user),
        "created_at": user.created_at,
        "exchange": user.exchange or "binance",
        "api_status": user.api_status,
        "is_active": user.is_active,
        "initial_principal": round(initial, 2),
        "live_equity": round(equity, 2),
        "available_balance": round(balance, 2),
        "cycle_pnl": cycle_pnl,
        "total_pnl": round(float(total_pnl), 2),
        "unrealized_pnl": round(unrealized, 2),
        "has_open_position": has_position,
        "position_side": position_side,
        "position_qty": position_qty,
        "position_entry": position_entry,
        "position_mark": position_mark,
        "settlement_status": settlement_status,
        "pending_perf_fee": pending_perf_fee,
        "pending_net_profit": pending_net_profit,
        "settlement_period": settlement_period,
        "settlement_id": settlement_id,
    }


def expected_referrer_reward(net_profit: float, level: int) -> float:
    if net_profit <= 0:
        return 0.0
    rate = settings.REFERRAL_L1_RATE if level == 1 else settings.REFERRAL_L2_RATE
    return round(net_profit * rate, 2)
