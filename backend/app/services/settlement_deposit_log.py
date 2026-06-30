"""Settlement deposit / payment log helpers for admin and user views."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import SettlementDeposit, Settlement, User, UserDepositAddress, SettlementPaymentAppeal
from app.services.user_lookup import display_name


def user_deposit_address(db: Session, user_id: int, chain: str) -> str | None:
    row = (
        db.query(UserDepositAddress)
        .filter(UserDepositAddress.user_id == user_id, UserDepositAddress.chain == chain.upper())
        .first()
    )
    return row.address if row else None


def fee_fully_paid(amount: float, payable: float | None) -> bool | None:
    if payable is None or payable <= 0:
        return None
    return amount + 0.01 >= payable * 0.98


def build_admin_deposit_row(db: Session, dep: SettlementDeposit) -> dict:
    user = db.query(User).filter(User.id == dep.user_id).first()
    settlement = None
    if dep.settlement_id:
        settlement = db.query(Settlement).filter(Settlement.id == dep.settlement_id).first()
    payable = float(settlement.user_payable or 0) if settlement else None
    return {
        "id": dep.id,
        "user_id": dep.user_id,
        "user_uid": user.uid if user else "",
        "user_display": display_name(user) if user else "",
        "settlement_id": dep.settlement_id,
        "settlement_payable": payable,
        "settlement_status": settlement.payment_status if settlement else None,
        "chain": dep.chain,
        "tx_hash": dep.tx_hash,
        "amount": dep.amount,
        "deposit_address": dep.deposit_address,
        "from_address": dep.from_address,
        "source": dep.source or "auto",
        "status": dep.status,
        "fee_fully_paid": fee_fully_paid(dep.amount, payable),
        "detected_at": dep.detected_at,
        "matched_at": dep.matched_at,
    }


def build_admin_appeal_row(db: Session, appeal: SettlementPaymentAppeal) -> dict:
    user = db.query(User).filter(User.id == appeal.user_id).first()
    settlement = db.query(Settlement).filter(Settlement.id == appeal.settlement_id).first()
    payable = float(settlement.user_payable or 0) if settlement else None
    return {
        "id": appeal.id,
        "user_id": appeal.user_id,
        "user_uid": user.uid if user else "",
        "user_display": display_name(user) if user else "",
        "settlement_id": appeal.settlement_id,
        "settlement_payable": payable,
        "settlement_status": settlement.payment_status if settlement else None,
        "chain": appeal.chain,
        "tx_hash": appeal.tx_hash,
        "claimed_amount": appeal.claimed_amount,
        "deposit_address": appeal.deposit_address,
        "user_note": appeal.user_note,
        "status": appeal.status,
        "fee_fully_paid": fee_fully_paid(appeal.claimed_amount, payable),
        "admin_note": appeal.admin_note,
        "reviewed_at": appeal.reviewed_at,
        "created_at": appeal.created_at,
    }
