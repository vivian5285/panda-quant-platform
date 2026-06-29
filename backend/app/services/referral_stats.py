"""Referral downline financial snapshot for promoters."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User, Trade, Settlement, PaymentStatus, ApiStatus
from app.services.dispatcher import supervisor_pool
from app.services.principal import fetch_live_equity
from app.services.settlement import get_pending_settlement, user_has_open_position
from app.services.user_lookup import display_name


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

    supervisor = supervisor_pool.get(user.id)
    if supervisor:
        try:
            summary = supervisor.client.get_futures_account_summary()
            equity = float(summary.get("total_margin_balance", 0))
            balance = float(summary.get("available_balance", equity))
            status = supervisor.position_manager.get_position_status()
            has_position = bool(status.get("has_position"))
            if has_position:
                unrealized = float(status.get("unrealized_pnl", 0))
                position_side = status.get("side")
                position_qty = float(status.get("quantity", 0))
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

    return {
        "id": user.id,
        "uid": user.uid or "",
        "email": _mask_identity(user),
        "display_name": display_name(user),
        "created_at": user.created_at,
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
        "settlement_status": settlement_status,
    }
