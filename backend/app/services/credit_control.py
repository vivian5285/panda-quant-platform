"""Credit-default (失信) controls: unpaid performance fees and master-family cascade."""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import ExchangeAccountRegistry, User
from app.services.settlement import user_has_unsettled_payment
from app.services.trading_control import get_user_control


def user_is_credit_default(db: Session, user_id: int) -> bool:
    """True when user has a performance fee bill awaiting payment or confirmation."""
    return user_has_unsettled_payment(db, user_id)


def user_credit_default_blocks_referral(db: Session, user_id: int) -> bool:
    """失信用户不可推广拉新（有未结绩效费即禁止，含管理员暂缓交易的情况）。"""
    return user_is_credit_default(db, user_id)


def _normalize_uid(val: str | None) -> str:
    return (val or "").strip()


def resolve_master_exchange_uid(user: User) -> str | None:
    uid = _normalize_uid(user.master_exchange_uid) or _normalize_uid(user.exchange_uid)
    return uid or None


def get_family_user_ids(db: Session, exchange: str, master_uid: str) -> list[int]:
    """Platform user IDs sharing the same exchange master UID family."""
    uid = _normalize_uid(master_uid)
    if not uid:
        return []

    reg_rows = (
        db.query(ExchangeAccountRegistry.user_id)
        .filter(
            ExchangeAccountRegistry.exchange == exchange,
            ExchangeAccountRegistry.is_active.is_(True),
            or_(
                ExchangeAccountRegistry.master_exchange_uid == uid,
                (
                    (ExchangeAccountRegistry.account_mode == "master")
                    & (ExchangeAccountRegistry.exchange_uid == uid)
                ),
            ),
        )
        .distinct()
        .all()
    )
    ids = {r[0] for r in reg_rows}

    # Include users with master/sub fields set but registry not yet written
    extra = (
        db.query(User.id)
        .filter(
            User.exchange == exchange,
            or_(
                User.master_exchange_uid == uid,
                (User.exchange_uid == uid) & (User.api_account_mode == "master"),
                User.exchange_uid == uid,
            ),
        )
        .all()
    )
    ids.update(r[0] for r in extra)
    return list(ids)


def family_has_credit_default_trading_block(
    db: Session,
    exchange: str,
    master_uid: str,
) -> bool:
    """Any family member has unpaid perf fee and is not admin-deferred → block whole family trading."""
    for user_id in get_family_user_ids(db, exchange, master_uid):
        if not user_is_credit_default(db, user_id):
            continue
        ctrl = get_user_control(db, user_id)
        if ctrl.get("settlement_fee_deferred"):
            continue
        return True
    return False


def user_trading_blocked_by_credit(db: Session, user_id: int) -> tuple[bool, str | None]:
    """
    Returns (blocked, reason).
    Blocks own unpaid bill (unless deferred) or any family member's unpaid bill (unless deferred).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False, None

    if user_is_credit_default(db, user_id):
        ctrl = get_user_control(db, user_id)
        if not ctrl.get("settlement_fee_deferred"):
            return True, "settlement_blocked"

    master_uid = resolve_master_exchange_uid(user)
    exchange = user.exchange or "binance"
    if master_uid and family_has_credit_default_trading_block(db, exchange, master_uid):
        return True, "family_credit_default"

    return False, None


def is_master_uid_credit_blocked(db: Session, exchange: str, master_uid: str) -> bool:
    """Bind-time: reject if master UID family has unpaid performance fee (non-deferred)."""
    return family_has_credit_default_trading_block(db, exchange, _normalize_uid(master_uid))


def is_master_uid_inactive_blocked(db: Session, exchange: str, master_uid: str) -> bool:
    """Bind-time: reject if master UID tied to a deactivated platform account."""
    uid = _normalize_uid(master_uid)
    if not uid:
        return False
    rows = (
        db.query(ExchangeAccountRegistry)
        .join(User, User.id == ExchangeAccountRegistry.user_id)
        .filter(
            ExchangeAccountRegistry.exchange == exchange,
            ExchangeAccountRegistry.is_active.is_(True),
            User.is_active.is_(False),
        )
        .filter(
            or_(
                ExchangeAccountRegistry.master_exchange_uid == uid,
                (
                    (ExchangeAccountRegistry.account_mode == "master")
                    & (ExchangeAccountRegistry.exchange_uid == uid)
                ),
            )
        )
        .all()
    )
    return len(rows) > 0


def is_master_uid_blocked(db: Session, exchange: str, master_uid: str) -> bool:
    """Bind-time: inactive family or credit-default family."""
    return (
        is_master_uid_inactive_blocked(db, exchange, master_uid)
        or is_master_uid_credit_blocked(db, exchange, master_uid)
    )
