from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.models.platform import SubscriptionPlan, UserSubscription, Invoice
from app.api.deps import get_current_user, get_admin_user
from app.services.audit import log_audit
from app.services.notification import notify_user
from app.services.alert_service import notify_system

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/plans")
def list_plans(db: Session = Depends(get_db)):
    rows = db.query(SubscriptionPlan).filter(SubscriptionPlan.is_active == True).order_by(SubscriptionPlan.sort_order).all()
    if not rows:
        return [
            {"code": "starter", "name": "Starter", "price_usd": 0, "features": ["7/10 day settlement", "Binance API", "Basic analytics"]},
            {"code": "pro", "name": "Pro", "price_usd": 99, "features": ["Lower fee share", "Advanced analytics", "Priority signals"]},
            {"code": "vip", "name": "VIP", "price_usd": 299, "features": ["Custom strategies", "1-on-1 support", "Dedicated webhook"]},
        ]
    import json
    return [{"code": p.code, "name": p.name, "price_usd": p.price_usd, "features": json.loads(p.features_json or "[]")} for p in rows]


@router.get("/subscription")
def my_subscription(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = db.query(UserSubscription).filter(UserSubscription.user_id == user.id, UserSubscription.status == "active").order_by(UserSubscription.started_at.desc()).first()
    if not sub:
        return {"plan_code": "starter", "status": "active", "expires_at": None}
    return {"plan_code": sub.plan_code, "status": sub.status, "expires_at": sub.expires_at.isoformat() if sub.expires_at else None}


@router.post("/subscribe")
def subscribe(body: dict, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan_code = body.get("plan_code") or "starter"
    amount = {"starter": 0, "pro": 99, "vip": 299}.get(plan_code, 0)
    inv = Invoice(user_id=user.id, plan_code=plan_code, amount=amount, status="pending" if amount > 0 else "paid", payment_method=body.get("payment_method") or "crypto")
    db.add(inv)
    if amount == 0:
        db.add(UserSubscription(user_id=user.id, plan_code=plan_code, status="active", expires_at=datetime.utcnow() + timedelta(days=365)))
        notify_user(db, user.id, "Subscription Active", f"Your {plan_code} plan is now active.", "billing")
    db.commit()
    log_audit(db, "billing.subscribe", user_id=user.id, detail={"plan": plan_code, "invoice_id": inv.id}, request=request)
    return {"invoice_id": inv.id, "status": inv.status, "amount": amount, "payment_method": inv.payment_method}


@router.post("/invoices/{invoice_id}/pay")
def pay_invoice(invoice_id: int, body: dict, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Submit payment proof. Paid plans require admin confirmation before activation."""
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.user_id == user.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status == "paid":
        return {"ok": True, "status": "paid", "message": "Already confirmed"}
    if inv.status == "submitted":
        return {"ok": True, "status": "submitted", "message": "Awaiting admin confirmation"}

    tx_hash = str(body.get("tx_hash") or "").strip()
    if inv.amount > 0 and not tx_hash:
        raise HTTPException(400, "tx_hash required for paid plans")

    if inv.amount <= 0:
        inv.status = "paid"
        inv.paid_at = datetime.utcnow()
        db.add(UserSubscription(user_id=user.id, plan_code=inv.plan_code or "starter", status="active", expires_at=datetime.utcnow() + timedelta(days=365)))
        notify_user(db, user.id, "Subscription Active", f"Invoice #{inv.id} activated.", "billing")
    else:
        inv.tx_hash = tx_hash
        inv.status = "submitted"
        notify_user(db, user.id, "Payment Submitted", f"Invoice #{inv.id} submitted for review.", "billing")
        notify_system(
            "info", "BILLING_SUBMIT",
            "订阅账单待确认",
            f"用户 {user.uid} 提交 Invoice #{inv.id} · {inv.plan_code} · ${inv.amount}",
            {"invoice_id": inv.id, "user_id": user.id, "tx_hash": tx_hash},
        )

    log_audit(db, "billing.pay_submit", user_id=user.id, detail={"invoice_id": inv.id, "tx_hash": tx_hash}, request=request)
    db.commit()
    return {"ok": True, "status": inv.status}


@router.get("/invoices")
def list_invoices(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Invoice).filter(Invoice.user_id == user.id).order_by(Invoice.created_at.desc()).limit(50).all()
    return [{"id": i.id, "plan_code": i.plan_code, "amount": i.amount, "currency": i.currency, "status": i.status, "payment_method": i.payment_method, "tx_hash": i.tx_hash, "created_at": i.created_at.isoformat(), "paid_at": i.paid_at.isoformat() if i.paid_at else None} for i in rows]


@router.get("/admin/invoices/pending")
def list_pending_invoices(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.query(Invoice).filter(Invoice.status == "submitted").order_by(Invoice.created_at.desc()).limit(100).all()
    return [{"id": i.id, "user_id": i.user_id, "plan_code": i.plan_code, "amount": i.amount, "tx_hash": i.tx_hash, "created_at": i.created_at.isoformat()} for i in rows]


@router.post("/admin/invoices/{invoice_id}/confirm")
def confirm_invoice(invoice_id: int, request: Request, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status == "paid":
        return {"ok": True, "status": "paid"}
    if inv.status != "submitted":
        raise HTTPException(400, "Invoice is not awaiting confirmation")

    inv.status = "paid"
    inv.paid_at = datetime.utcnow()
    db.query(UserSubscription).filter(UserSubscription.user_id == inv.user_id).update({"status": "expired"})
    db.add(UserSubscription(
        user_id=inv.user_id,
        plan_code=inv.plan_code or "pro",
        status="active",
        expires_at=datetime.utcnow() + timedelta(days=30),
    ))
    notify_user(db, inv.user_id, "Payment Confirmed", f"Invoice #{inv.id} confirmed. Plan activated.", "billing")
    log_audit(db, "billing.confirm", actor_id=admin.id, user_id=inv.user_id, detail={"invoice_id": inv.id}, request=request)
    db.commit()
    return {"ok": True, "status": "paid"}
