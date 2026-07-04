"""Performance-fee payment tracking for users and admins."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    PaymentStatus,
    ReferralReward,
    Settlement,
    SettlementDeposit,
    SettlementPaymentAppeal,
    User,
    UserDepositAddress,
)
from app.services.deposit_monitor_state import get_deposit_monitor_status
from app.services.settlement_deposit_log import fee_fully_paid
from app.services.user_lookup import display_name
from app.services.wallet_balance import fetch_address_balance

settings = get_settings()


def fee_split_breakdown(net_profit: float) -> dict:
    base = round(float(net_profit or 0), 2)
    payable = round(base * settings.PLATFORM_FEE_RATE, 2)
    l1 = round(base * settings.REFERRAL_L1_RATE, 2)
    l2 = round(base * settings.REFERRAL_L2_RATE, 2)
    platform_net = round(payable - l1 - l2, 2)
    return {
        "net_profit": base,
        "user_payable": payable,
        "l1_reward": l1,
        "l2_reward": l2,
        "platform_net": platform_net,
        "l1_rate": settings.REFERRAL_L1_RATE,
        "l2_rate": settings.REFERRAL_L2_RATE,
        "platform_fee_rate": settings.PLATFORM_FEE_RATE,
    }


def _tracking_phase(
    settlement: Settlement,
    deposits: list[SettlementDeposit],
    appeal: SettlementPaymentAppeal | None,
) -> str:
    status = settlement.payment_status
    if status == PaymentStatus.CONFIRMED.value:
        return "confirmed"
    if status == PaymentStatus.REJECTED.value:
        return "rejected"
    if appeal and appeal.status == "submitted":
        return "appeal_pending"
    if status == PaymentStatus.PAID.value:
        return "paid" if not settings.SETTLEMENT_AUTO_CONFIRM else "confirming"
    payable = float(settlement.user_payable or 0)
    matched = [d for d in deposits if d.status == "matched" and d.settlement_id == settlement.id]
    if matched:
        return "matched_unconfirmed"
    detected = [d for d in deposits if d.status == "detected"]
    if detected:
        max_amt = max(d.amount for d in detected)
        if fee_fully_paid(max_amt, payable):
            return "amount_ok_detecting"
        return "underpaid"
    return "awaiting_transfer"


def _deposit_addresses(db: Session, user_id: int) -> list[dict]:
    rows = (
        db.query(UserDepositAddress)
        .filter(UserDepositAddress.user_id == user_id)
        .order_by(UserDepositAddress.chain)
        .all()
    )
    return [{"chain": r.chain, "address": r.address} for r in rows]


def _probe_balances(addresses: list[dict]) -> list[dict]:
    out = []
    for item in addresses:
        bal = fetch_address_balance(item["chain"], item["address"])
        out.append({
            "chain": item["chain"],
            "address": item["address"],
            "usdt_balance": bal.usdt,
            "rpc_ready": bal.rpc_ready,
            "error": bal.error,
        })
    return out


def _referral_preview(db: Session, settlement_id: int) -> list[dict]:
    rewards = (
        db.query(ReferralReward)
        .filter(ReferralReward.settlement_id == settlement_id)
        .order_by(ReferralReward.level)
        .all()
    )
    out = []
    for r in rewards:
        ref = db.query(User).filter(User.id == r.referrer_id).first()
        out.append({
            "level": r.level,
            "referrer_uid": ref.uid if ref else "",
            "referrer_display": display_name(ref) if ref else "",
            "reward_amount": r.reward_amount,
            "status": r.status,
        })
    return out


def build_tracking_row(
    db: Session,
    settlement: Settlement,
    *,
    probe: bool = False,
) -> dict:
    user = db.query(User).filter(User.id == settlement.user_id).first()
    deposits = (
        db.query(SettlementDeposit)
        .filter(SettlementDeposit.user_id == settlement.user_id)
        .order_by(SettlementDeposit.detected_at.desc())
        .limit(20)
        .all()
    )
    appeal = (
        db.query(SettlementPaymentAppeal)
        .filter(
            SettlementPaymentAppeal.settlement_id == settlement.id,
            SettlementPaymentAppeal.status == "submitted",
        )
        .first()
    )
    addresses = _deposit_addresses(db, settlement.user_id)
    phase = _tracking_phase(settlement, deposits, appeal)
    payable = float(settlement.user_payable or 0)
    detected_total = sum(
        d.amount for d in deposits
        if d.status in ("detected", "matched")
        and (d.settlement_id is None or d.settlement_id == settlement.id)
    )
    row = {
        "settlement_id": settlement.id,
        "user_id": settlement.user_id,
        "user_uid": user.uid if user else "",
        "user_display": display_name(user) if user else "",
        "payment_status": settlement.payment_status,
        "tracking_phase": phase,
        "user_payable": payable,
        "net_profit": settlement.net_profit,
        "detected_total": round(detected_total, 2),
        "amount_sufficient": fee_fully_paid(detected_total, payable) if payable > 0 else None,
        "payment_chain": settlement.payment_chain,
        "payment_tx_hash": settlement.payment_tx_hash,
        "payment_amount": settlement.payment_amount,
        "paid_at": settlement.paid_at,
        "confirmed_at": settlement.confirmed_at,
        "period_start": str(settlement.period_start),
        "period_end": str(settlement.period_end),
        "deposit_addresses": addresses,
        "split": fee_split_breakdown(float(settlement.net_profit or 0)),
        "referral_rewards": _referral_preview(db, settlement.id),
        "appeal_id": appeal.id if appeal else None,
        "appeal_status": appeal.status if appeal else None,
        "recent_deposits": [
            {
                "id": d.id,
                "chain": d.chain,
                "amount": d.amount,
                "tx_hash": d.tx_hash,
                "status": d.status,
                "source": d.source,
                "detected_at": d.detected_at,
                "deposit_address": d.deposit_address,
            }
            for d in deposits[:5]
        ],
    }
    if probe and phase in ("awaiting_transfer", "underpaid", "amount_ok_detecting", "appeal_pending"):
        row["on_chain_balances"] = _probe_balances(addresses)
    return row


def get_user_payment_tracking(db: Session, user_id: int, *, probe: bool = True) -> dict | None:
    settlement = (
        db.query(Settlement)
        .filter(
            Settlement.user_id == user_id,
            Settlement.payment_status.in_(
                (
                    PaymentStatus.PENDING.value,
                    PaymentStatus.PAID.value,
                    PaymentStatus.REJECTED.value,
                )
            ),
        )
        .order_by(Settlement.created_at.desc())
        .first()
    )
    if not settlement:
        return None
    monitor = get_deposit_monitor_status()
    row = build_tracking_row(db, settlement, probe=probe)
    row["monitor_health"] = monitor["health"]
    row["last_scan_at"] = monitor.get("last_scan_at")
    row["scan_interval_sec"] = monitor.get("scan_interval_sec")
    return row


def list_admin_payment_tracking(
    db: Session,
    *,
    probe: bool = False,
    limit: int = 100,
) -> list[dict]:
    rows = (
        db.query(Settlement)
        .filter(
            Settlement.payment_status.in_(
                (
                    PaymentStatus.PENDING.value,
                    PaymentStatus.PAID.value,
                )
            )
        )
        .order_by(Settlement.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [build_tracking_row(db, s, probe=probe) for s in rows]


def count_tracking_anomalies(db: Session) -> int:
    """Settlements pending >6h with no matched deposit and no appeal."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = (
        db.query(Settlement)
        .filter(Settlement.payment_status == PaymentStatus.PENDING.value)
        .all()
    )
    count = 0
    for s in rows:
        age_hours = (cutoff - (s.created_at or cutoff)).total_seconds() / 3600
        if age_hours < 6:
            continue
        has_matched = (
            db.query(SettlementDeposit)
            .filter(
                SettlementDeposit.user_id == s.user_id,
                SettlementDeposit.status == "matched",
                SettlementDeposit.settlement_id == s.id,
            )
            .first()
        )
        if has_matched:
            continue
        appeal = (
            db.query(SettlementPaymentAppeal)
            .filter(
                SettlementPaymentAppeal.settlement_id == s.id,
                SettlementPaymentAppeal.status == "submitted",
            )
            .first()
        )
        if appeal:
            continue
        count += 1
    return count
