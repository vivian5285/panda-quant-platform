"""Admin settlement billing summary and cycle pipeline stats."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ApiStatus, PaymentStatus, Settlement, User
from app.services.settlement import get_pending_settlement, user_has_unsettled_payment
from app.services.user_lookup import display_name

settings = get_settings()


def _status_amounts(db: Session) -> dict[str, float]:
    rows = (
        db.query(Settlement.payment_status, func.coalesce(func.sum(Settlement.user_payable), 0))
        .group_by(Settlement.payment_status)
        .all()
    )
    return {status: round(float(amt or 0), 2) for status, amt in rows}


def _users_approaching_cycle(db: Session, *, within_days: int = 7) -> list[dict]:
    today = date.today()
    users = (
        db.query(User)
        .filter(User.is_active == True, User.api_status == ApiStatus.ACTIVE.value)
        .all()
    )
    out: list[dict] = []
    for u in users:
        if user_has_unsettled_payment(db, u.id):
            continue
        if not u.settlement_cycle_start:
            continue
        target = int(u.settlement_target_days or settings.SETTLEMENT_PRIMARY_DAYS)
        elapsed = (today - u.settlement_cycle_start).days
        days_left = target - elapsed
        if days_left < 0 or days_left > within_days:
            continue
        out.append({
            "user_id": u.id,
            "user_uid": u.uid,
            "user_display": display_name(u),
            "cycle_start": u.settlement_cycle_start.isoformat(),
            "cycle_target_days": target,
            "days_elapsed": elapsed,
            "days_until_due": max(0, days_left),
            "initial_principal": float(u.initial_principal or 0),
        })
    out.sort(key=lambda x: x["days_until_due"])
    return out


def build_settlement_admin_summary(db: Session) -> dict:
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    total_bills = db.query(Settlement).count()
    by_status = {
        row[0]: int(row[1])
        for row in (
            db.query(Settlement.payment_status, func.count(Settlement.id))
            .group_by(Settlement.payment_status)
            .all()
        )
    }
    amounts = _status_amounts(db)

    pending_count = int(by_status.get(PaymentStatus.PENDING.value, 0))
    paid_count = int(by_status.get(PaymentStatus.PAID.value, 0))
    confirmed_count = int(by_status.get(PaymentStatus.CONFIRMED.value, 0))
    rejected_count = int(by_status.get(PaymentStatus.REJECTED.value, 0))

    unpaid_users = (
        db.query(func.count(func.distinct(Settlement.user_id)))
        .filter(Settlement.payment_status == PaymentStatus.PENDING.value)
        .scalar()
        or 0
    )

    today_created = (
        db.query(Settlement)
        .filter(Settlement.created_at >= today_start)
        .count()
    )
    today_confirmed = (
        db.query(Settlement)
        .filter(
            Settlement.payment_status == PaymentStatus.CONFIRMED.value,
            Settlement.confirmed_at >= today_start,
        )
        .count()
    )

    approaching = _users_approaching_cycle(db)

    return {
        "total_bills": total_bills,
        "pending_payment": pending_count,
        "paid_awaiting_confirm": paid_count,
        "confirmed": confirmed_count,
        "rejected": rejected_count,
        "unpaid_users": int(unpaid_users),
        "pending_amount_total": amounts.get(PaymentStatus.PENDING.value, 0),
        "paid_amount_total": amounts.get(PaymentStatus.PAID.value, 0),
        "confirmed_amount_total": amounts.get(PaymentStatus.CONFIRMED.value, 0),
        "today_new_bills": today_created,
        "today_confirmed": today_confirmed,
        "approaching_cycle_count": len(approaching),
        "approaching_cycle_users": approaching[:50],
    }


def build_admin_settlement_row(db: Session, s: Settlement) -> dict:
    from app.services.trading_control import get_user_control

    user = db.query(User).filter(User.id == s.user_id).first()
    pending = get_pending_settlement(db, s.user_id)
    deferred = False
    if pending and pending.id == s.id:
        deferred = bool(get_user_control(db, s.user_id).get("settlement_fee_deferred"))
    return {
        "id": s.id,
        "user_id": s.user_id,
        "user_uid": user.uid if user else "",
        "user_display": display_name(user) if user else "",
        "period_start": s.period_start,
        "period_end": s.period_end,
        "gross_profit": s.gross_profit or 0.0,
        "net_profit": s.net_profit,
        "high_water_mark": s.high_water_mark or 0.0,
        "platform_fee": s.platform_fee,
        "user_payable": s.user_payable,
        "cycle_days": s.cycle_days or 30,
        "payment_status": s.payment_status,
        "payment_chain": s.payment_chain,
        "payment_tx_hash": s.payment_tx_hash,
        "payment_amount": s.payment_amount,
        "paid_at": s.paid_at,
        "confirmed_at": s.confirmed_at,
        "created_at": s.created_at,
        "settlement_fee_deferred": deferred,
    }
