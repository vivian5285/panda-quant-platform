"""User payment appeals when auto deposit detection fails."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import SettlementPaymentAppeal, SettlementDeposit, Settlement, PaymentStatus, User
from app.services.settlement import submit_settlement_payment, get_pending_settlement
from app.services.settlement_deposit_log import user_deposit_address

logger = logging.getLogger(__name__)


def _normalize_tx(tx_hash: str) -> str:
    return tx_hash.strip()


def create_payment_appeal(
    db: Session,
    user: User,
    settlement_id: int,
    chain: str,
    tx_hash: str,
    claimed_amount: float,
    user_note: str = "",
) -> SettlementPaymentAppeal:
    settlement = db.query(Settlement).filter(
        Settlement.id == settlement_id,
        Settlement.user_id == user.id,
    ).first()
    if not settlement:
        raise ValueError("结算单不存在")
    if settlement.payment_status not in (
        PaymentStatus.PENDING.value,
        PaymentStatus.REJECTED.value,
    ):
        raise ValueError("当前结算单状态不可申诉")

    normalized = _normalize_tx(tx_hash)
    if len(normalized) < 8:
        raise ValueError("TxHash 无效")

    pending = db.query(SettlementPaymentAppeal).filter(
        SettlementPaymentAppeal.settlement_id == settlement_id,
        SettlementPaymentAppeal.status == "submitted",
    ).first()
    if pending:
        raise ValueError("已有待审核申诉，请等待管理员处理")

    appeal = SettlementPaymentAppeal(
        user_id=user.id,
        settlement_id=settlement_id,
        chain=chain.upper(),
        tx_hash=normalized,
        claimed_amount=round(claimed_amount, 2),
        deposit_address=user_deposit_address(db, user.id, chain),
        user_note=(user_note or "").strip() or None,
        status="submitted",
    )
    db.add(appeal)
    db.commit()
    db.refresh(appeal)

    from app.services.alert_service import notify_system
    notify_system(
        "warning",
        "SETTLEMENT_APPEAL",
        f"用户 {user.uid} 提交绩效费缴纳申诉",
        f"结算单 #{settlement_id} · {chain.upper()} · ${claimed_amount:.2f} · {normalized[:16]}…",
        {
            "user_id": user.id,
            "uid": user.uid,
            "settlement_id": settlement_id,
            "chain": chain.upper(),
            "tx_hash": normalized,
            "claimed_amount": claimed_amount,
        },
    )
    return appeal


def approve_payment_appeal(
    db: Session,
    appeal: SettlementPaymentAppeal,
    admin_id: int,
    admin_note: str = "",
) -> SettlementPaymentAppeal:
    if appeal.status != "submitted":
        raise ValueError("申诉已处理")

    settlement = db.query(Settlement).filter(Settlement.id == appeal.settlement_id).first()
    if not settlement:
        raise ValueError("结算单不存在")

    user = db.query(User).filter(User.id == appeal.user_id).first()
    if not user:
        raise ValueError("用户不存在")

    dep = db.query(SettlementDeposit).filter(
        SettlementDeposit.tx_hash == appeal.tx_hash
    ).first()
    if not dep:
        dep = SettlementDeposit(
            user_id=appeal.user_id,
            chain=appeal.chain,
            tx_hash=appeal.tx_hash,
            amount=appeal.claimed_amount,
            deposit_address=appeal.deposit_address,
            source="appeal",
            status="detected",
        )
        db.add(dep)
        db.flush()

    submit_settlement_payment(
        db,
        settlement,
        appeal.chain,
        appeal.tx_hash,
        min(appeal.claimed_amount, float(settlement.user_payable or 0)),
    )

    dep.settlement_id = settlement.id
    dep.status = "matched"
    dep.matched_at = datetime.utcnow()
    dep.source = "appeal"

    appeal.status = "approved"
    appeal.admin_note = admin_note or None
    appeal.reviewed_by = admin_id
    appeal.reviewed_at = datetime.utcnow()
    appeal.settlement_deposit_id = dep.id

    from app.services.trade_logger import TradeLogger
    TradeLogger(db).log_event(
        user.id,
        "SETTLEMENT",
        f"绩效费缴纳申诉已通过，结算单 #{settlement.id} 待管理员确认到账",
        {"settlement_id": settlement.id, "tx_hash": appeal.tx_hash, "appeal_id": appeal.id},
    )

    db.commit()
    db.refresh(appeal)
    return appeal


def reject_payment_appeal(
    db: Session,
    appeal: SettlementPaymentAppeal,
    admin_id: int,
    admin_note: str = "",
) -> SettlementPaymentAppeal:
    if appeal.status != "submitted":
        raise ValueError("申诉已处理")
    appeal.status = "rejected"
    appeal.admin_note = admin_note or "rejected"
    appeal.reviewed_by = admin_id
    appeal.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(appeal)
    return appeal
