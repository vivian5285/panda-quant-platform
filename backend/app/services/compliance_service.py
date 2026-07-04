"""Admin compliance views: sub-account filings, referral blocks, audit trail."""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import ExchangeSubAccountFiling, User
from app.services.credit_control import get_referral_block_details, referral_block_reason
from app.services.trading_control import get_user_control
from app.services.user_lookup import display_name
from app.models.platform import AuditLog


def list_sub_account_filings(
    db: Session,
    *,
    q: str | None = None,
    exchange: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    qry = (
        db.query(ExchangeSubAccountFiling, User)
        .join(User, User.id == ExchangeSubAccountFiling.user_id)
    )
    if exchange:
        qry = qry.filter(ExchangeSubAccountFiling.exchange == exchange.strip().lower())
    if q and q.strip():
        needle = f"%{q.strip()}%"
        qry = qry.filter(
            or_(
                ExchangeSubAccountFiling.master_exchange_uid.ilike(needle),
                ExchangeSubAccountFiling.sub_exchange_uid.ilike(needle),
                ExchangeSubAccountFiling.sub_label.ilike(needle),
                User.uid.ilike(needle),
                User.email.ilike(needle),
                User.display_name.ilike(needle),
            )
        )
    rows = (
        qry.order_by(ExchangeSubAccountFiling.filed_at.desc())
        .offset(max(offset, 0))
        .limit(min(limit, 500))
        .all()
    )
    return [
        {
            "id": f.id,
            "user_id": f.user_id,
            "platform_uid": u.uid or "",
            "display_name": display_name(u),
            "exchange": f.exchange,
            "master_exchange_uid": f.master_exchange_uid,
            "sub_exchange_uid": f.sub_exchange_uid,
            "sub_label": f.sub_label or "",
            "is_active": bool(f.is_active),
            "filed_at": f.filed_at,
        }
        for f, u in rows
    ]


def list_user_sub_account_filings(db: Session, user_id: int) -> list[dict]:
    rows = (
        db.query(ExchangeSubAccountFiling)
        .filter(
            ExchangeSubAccountFiling.user_id == user_id,
            ExchangeSubAccountFiling.is_active.is_(True),
        )
        .order_by(ExchangeSubAccountFiling.sub_exchange_uid.asc())
        .all()
    )
    return [
        {
            "id": f.id,
            "exchange": f.exchange,
            "master_exchange_uid": f.master_exchange_uid,
            "sub_exchange_uid": f.sub_exchange_uid,
            "sub_label": f.sub_label or "",
            "filed_at": f.filed_at,
        }
        for f in rows
    ]


def list_referral_blocks(
    db: Session,
    *,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Users currently blocked from referral invites."""
    qry = db.query(User).filter(User.is_active.is_(True))
    if q and q.strip():
        needle = f"%{q.strip()}%"
        qry = qry.filter(
            or_(
                User.uid.ilike(needle),
                User.email.ilike(needle),
                User.display_name.ilike(needle),
            )
        )
    results: list[dict] = []
    skip = max(offset, 0)
    scanned = 0
    for u in qry.order_by(User.id.desc()).limit(2000):
        reason = referral_block_reason(db, u.id)
        if not reason:
            continue
        if skip > 0:
            skip -= 1
            continue
        ctrl = get_user_control(db, u.id)
        results.append({
            "user_id": u.id,
            "platform_uid": u.uid or "",
            "display_name": display_name(u),
            "referral_block_reason": reason,
            "referral_invite_override": bool(ctrl.get("referral_invite_override")),
            "referral_override_note": ctrl.get("referral_override_note") or "",
            "details": get_referral_block_details(db, u.id),
        })
        if len(results) >= min(limit, 200):
            break
        scanned += 1
        if scanned > 1500:
            break
    return results


def list_compliance_audit_logs(
    db: Session,
    *,
    q: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Compliance-related audit entries (API bind, referral override, trading control)."""
    actions = (
        "api.bind",
        "api.unbind",
        "admin.trading_control",
    )
    qry = db.query(AuditLog).filter(AuditLog.action.in_(actions))
    if q and q.strip():
        needle = f"%{q.strip()}%"
        qry = qry.filter(
            or_(
                AuditLog.action.ilike(needle),
                AuditLog.detail_json.ilike(needle),
                AuditLog.resource_id.ilike(needle),
            )
        )
    rows = qry.order_by(AuditLog.created_at.desc()).limit(min(limit, 500)).all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "user_id": r.user_id,
            "actor_id": r.actor_id,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "detail_json": r.detail_json,
            "ip_address": r.ip_address,
            "created_at": r.created_at,
        }
        for r in rows
    ]
