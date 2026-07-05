"""Credit-default (失信) controls: unpaid performance fees and master-family cascade."""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import ApiStatus, ExchangeAccountRegistry, ExchangeSubAccountFiling, User
from app.services.settlement import user_has_unsettled_payment
from app.services.trading_control import get_user_control


def user_is_credit_default(db: Session, user_id: int) -> bool:
    """True when user has a performance fee bill awaiting payment or confirmation."""
    return user_has_unsettled_payment(db, user_id)


def user_referral_invite_override(db: Session, user_id: int) -> bool:
    """Admin-granted exception to invite despite credit-default rules."""
    return bool(get_user_control(db, user_id).get("referral_invite_override"))


def get_downline_user_ids(db: Session, user_id: int, max_depth: int = 2) -> list[int]:
    """L1 + L2 downline platform user IDs."""
    l1_rows = db.query(User.id).filter(User.referrer_id == user_id).all()
    l1_ids = [r[0] for r in l1_rows]
    if max_depth < 2 or not l1_ids:
        return l1_ids
    l2_rows = db.query(User.id).filter(User.referrer_id.in_(l1_ids)).all()
    return l1_ids + [r[0] for r in l2_rows]


def downline_has_credit_default(db: Session, user_id: int) -> bool:
    """Any L1/L2 downline has unpaid performance fee."""
    for did in get_downline_user_ids(db, user_id):
        if user_is_credit_default(db, did):
            return True
    return False


def get_referral_block_details(db: Session, user_id: int) -> list[dict]:
    """Per-user breakdown for referral block UI (own unpaid or which downlines)."""
    reason = referral_block_reason(db, user_id)
    if not reason:
        return []

    from app.services.referral_stats import build_downline_stats
    from app.services.user_lookup import display_name

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return []

    def _row(u: User, level: int, scope: str) -> dict:
        stats = build_downline_stats(db, u)
        return {
            "user_id": u.id,
            "platform_uid": u.uid or "",
            "display_name": display_name(u),
            "level": level,
            "scope": scope,
            "pending_perf_fee": round(float(stats.get("pending_perf_fee") or 0), 2),
            "settlement_status": stats.get("settlement_status"),
            "exchange": stats.get("exchange", "binance"),
        }

    if reason == "own_credit_default":
        return [_row(user, 0, "own")]

    out: list[dict] = []
    l1_rows = db.query(User).filter(User.referrer_id == user_id).all()
    for u in l1_rows:
        if user_is_credit_default(db, u.id):
            out.append(_row(u, 1, "downline"))
    l1_ids = [u.id for u in l1_rows]
    if l1_ids:
        for u in db.query(User).filter(User.referrer_id.in_(l1_ids)).all():
            if user_is_credit_default(db, u.id):
                out.append(_row(u, 2, "downline"))
    return out


def referral_block_reason(db: Session, user_id: int) -> str | None:
    """
    Why referral sharing is blocked.
    Returns: own_credit_default | downline_credit_default | None
    """
    if user_referral_invite_override(db, user_id):
        return None
    if user_is_credit_default(db, user_id):
        return "own_credit_default"
    if downline_has_credit_default(db, user_id):
        return "downline_credit_default"
    return None


def user_credit_default_blocks_referral(db: Session, user_id: int) -> bool:
    """失信或下线未缴绩效费 → 禁止推广拉新（管理员可特批）。"""
    return referral_block_reason(db, user_id) is not None


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
    for uid in get_family_user_ids(db, exchange, master_uid):
        if not user_is_credit_default(db, uid):
            continue
        ctrl = get_user_control(db, uid)
        if ctrl.get("settlement_fee_deferred"):
            continue
        return True
    return False


def user_entry_blocked_by_settlement(db: Session, user_id: int) -> tuple[bool, str | None]:
    """Block new entries: unpaid bill, family default, or awaiting flat after profitable cycle."""
    from app.services.trading_control import get_user_control

    ctrl = get_user_control(db, user_id)
    if ctrl.get("settlement_awaiting_flat"):
        return True, "settlement_awaiting_flat"
    return user_trading_blocked_by_credit(db, user_id)


def user_api_bind_blocked(db: Session, user_id: int) -> tuple[bool, str | None]:
    """失信用户禁止绑定/重绑 API。"""
    if user_is_credit_default(db, user_id):
        ctrl = get_user_control(db, user_id)
        if not ctrl.get("settlement_fee_deferred"):
            return True, "own_credit_default"
    return False, None


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


def is_filed_sub_uid_taken(
    db: Session,
    exchange: str,
    sub_uid: str,
    exclude_user_id: int | None = None,
) -> bool:
    """Sub UID already filed under another active API user."""
    uid = _normalize_uid(sub_uid)
    if not uid:
        return False
    q = (
        db.query(ExchangeSubAccountFiling)
        .join(User, User.id == ExchangeSubAccountFiling.user_id)
        .filter(
            ExchangeSubAccountFiling.exchange == exchange,
            ExchangeSubAccountFiling.sub_exchange_uid == uid,
            ExchangeSubAccountFiling.is_active.is_(True),
            User.api_status == ApiStatus.ACTIVE.value,
        )
    )
    if exclude_user_id:
        q = q.filter(ExchangeSubAccountFiling.user_id != exclude_user_id)
    return q.first() is not None
