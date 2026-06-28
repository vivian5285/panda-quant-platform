from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    User, Trade, Settlement, ReferralReward, PaymentStatus, ApiStatus,
    PlatformDepositAddress, WithdrawalRequest, WithdrawalStatus, SUPPORTED_CHAINS,
    AdminAlert,
)
from app.schemas import (
    AdminUserOut, AdminOverview, SettlementOut,
    DepositAddressOut, DepositAddressCreate,
    WithdrawalOut, WithdrawalComplete, WithdrawalReject,
    AdminAlertOut,
)
from app.api.deps import get_admin_user
from app.services.dispatcher import supervisor_pool
from app.services.settlement import run_scheduled_settlements, confirm_settlement_payment
from app.services.wallet import complete_withdrawal, reject_withdrawal
from app.services.alert_service import list_alerts, mark_alert_read, mark_all_read

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverview)
def overview(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    return AdminOverview(
        total_users=db.query(User).count(),
        active_api_users=db.query(User).filter(User.api_status == ApiStatus.ACTIVE.value).count(),
        total_trades=db.query(Trade).count(),
        pending_settlements=db.query(Settlement).filter(
            Settlement.payment_status == PaymentStatus.PENDING.value
        ).count(),
        pending_payments=db.query(Settlement).filter(
            Settlement.payment_status == PaymentStatus.PAID.value
        ).count(),
        pending_withdrawals=db.query(WithdrawalRequest).filter(
            WithdrawalRequest.status.in_([
                WithdrawalStatus.PENDING.value,
                WithdrawalStatus.AUTO_APPROVED.value,
                WithdrawalStatus.APPROVED.value,
            ])
        ).count(),
        unread_alerts=db.query(AdminAlert).filter(AdminAlert.is_read == False).count(),
    )


@router.get("/users", response_model=list[AdminUserOut])
def list_users(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at.desc()).all()


@router.post("/users/{user_id}/toggle")
def toggle_user(user_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_active = not user.is_active
    db.commit()
    return {"id": user.id, "is_active": user.is_active}


@router.get("/settlements", response_model=list[SettlementOut])
def all_settlements(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    return db.query(Settlement).order_by(Settlement.created_at.desc()).limit(100).all()


@router.post("/settlements/run")
def trigger_settlement(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    created = run_scheduled_settlements(db)
    return {"created": len(created), "ids": [s.id for s in created]}


@router.post("/settlements/run-weekly")
def trigger_weekly_settlement(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    created = run_scheduled_settlements(db)
    return {"created": len(created), "ids": [s.id for s in created]}


@router.post("/settlements/{settlement_id}/confirm")
def confirm_settlement(settlement_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    s = db.query(Settlement).filter(Settlement.id == settlement_id).first()
    if not s:
        raise HTTPException(404, "Settlement not found")
    if s.payment_status not in (PaymentStatus.PAID.value, PaymentStatus.PENDING.value):
        raise HTTPException(400, "Settlement already confirmed or rejected")
    confirm_settlement_payment(db, s)
    return {"status": "confirmed"}


@router.post("/settlements/{settlement_id}/reject")
def reject_settlement(
    settlement_id: int,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    s = db.query(Settlement).filter(Settlement.id == settlement_id).first()
    if not s:
        raise HTTPException(404, "Settlement not found")
    s.payment_status = PaymentStatus.REJECTED.value
    db.commit()
    return {"status": "rejected"}


# --- Platform deposit addresses ---

@router.get("/deposit-addresses", response_model=list[DepositAddressOut])
def list_deposit_addresses(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    return db.query(PlatformDepositAddress).order_by(
        PlatformDepositAddress.sort_order, PlatformDepositAddress.id
    ).all()


@router.post("/deposit-addresses", response_model=DepositAddressOut)
def create_deposit_address(
    req: DepositAddressCreate,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    if req.chain.upper() not in SUPPORTED_CHAINS:
        raise HTTPException(400, f"Unsupported chain. Supported: {', '.join(SUPPORTED_CHAINS)}")
    addr = PlatformDepositAddress(
        chain=req.chain.upper(),
        address=req.address.strip(),
        label=req.label,
        sort_order=req.sort_order,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return addr


@router.post("/deposit-addresses/{addr_id}/toggle")
def toggle_deposit_address(addr_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    addr = db.query(PlatformDepositAddress).filter(PlatformDepositAddress.id == addr_id).first()
    if not addr:
        raise HTTPException(404, "Address not found")
    addr.is_active = not addr.is_active
    db.commit()
    return {"id": addr.id, "is_active": addr.is_active}


@router.delete("/deposit-addresses/{addr_id}")
def delete_deposit_address(addr_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    addr = db.query(PlatformDepositAddress).filter(PlatformDepositAddress.id == addr_id).first()
    if not addr:
        raise HTTPException(404, "Address not found")
    db.delete(addr)
    db.commit()
    return {"status": "ok"}


# --- Withdrawals ---

@router.get("/withdrawals", response_model=list[WithdrawalOut])
def list_withdrawals(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    return db.query(WithdrawalRequest).order_by(
        WithdrawalRequest.created_at.desc()
    ).limit(100).all()


@router.post("/withdrawals/{withdrawal_id}/approve")
def approve_withdrawal(withdrawal_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    req = db.query(WithdrawalRequest).filter(WithdrawalRequest.id == withdrawal_id).first()
    if not req:
        raise HTTPException(404, "Withdrawal not found")
    if req.status not in (WithdrawalStatus.PENDING.value, WithdrawalStatus.AUTO_APPROVED.value):
        raise HTTPException(400, "Withdrawal cannot be approved")
    req.status = WithdrawalStatus.APPROVED.value
    db.commit()
    return {"status": "approved"}


@router.post("/withdrawals/{withdrawal_id}/complete", response_model=WithdrawalOut)
def complete_withdrawal_route(
    withdrawal_id: int,
    body: WithdrawalComplete,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    req = db.query(WithdrawalRequest).filter(WithdrawalRequest.id == withdrawal_id).first()
    if not req:
        raise HTTPException(404, "Withdrawal not found")
    if req.status in (WithdrawalStatus.COMPLETED.value, WithdrawalStatus.REJECTED.value):
        raise HTTPException(400, "Withdrawal already processed")
    return complete_withdrawal(db, req, body.tx_hash.strip(), body.admin_note)


@router.post("/withdrawals/{withdrawal_id}/reject", response_model=WithdrawalOut)
def reject_withdrawal_route(
    withdrawal_id: int,
    body: WithdrawalReject,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    req = db.query(WithdrawalRequest).filter(WithdrawalRequest.id == withdrawal_id).first()
    if not req:
        raise HTTPException(404, "Withdrawal not found")
    if req.status in (WithdrawalStatus.COMPLETED.value, WithdrawalStatus.REJECTED.value):
        raise HTTPException(400, "Withdrawal already processed")
    return reject_withdrawal(db, req, body.admin_note)


@router.get("/startup-audit")
def startup_audit(admin=Depends(get_admin_user)):
    """VPS 自启账户接管审计结果（管理员查看）。"""
    return {
        "active_supervisors": len(supervisor_pool.get_all()),
        "audits": supervisor_pool.last_startup_audits,
        "failures": supervisor_pool.last_startup_failures,
    }


@router.get("/alerts", response_model=list[AdminAlertOut])
def get_alerts(
    unread_only: bool = False,
    limit: int = 100,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    alerts = list_alerts(db, unread_only=unread_only, limit=limit)
    out = []
    for a in alerts:
        user = db.query(User).filter(User.id == a.user_id).first() if a.user_id else None
        out.append(AdminAlertOut(
            id=a.id,
            user_id=a.user_id,
            uid=user.uid if user else None,
            severity=a.severity,
            alert_type=a.alert_type,
            title=a.title,
            message=a.message,
            detail_json=a.detail_json,
            is_read=a.is_read,
            created_at=a.created_at,
        ))
    return out


@router.post("/alerts/{alert_id}/read")
def read_alert(alert_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    if not mark_alert_read(db, alert_id):
        raise HTTPException(404, "Alert not found")
    return {"status": "ok"}


@router.post("/alerts/read-all")
def read_all_alerts(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    count = mark_all_read(db)
    return {"status": "ok", "marked": count}
