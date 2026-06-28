from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.models.platform import SubscriptionPlan, UserSubscription, Invoice
from app.api.deps import get_current_user
from app.services.audit import log_audit
from app.services.notification import notify_user

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
def pay_invoice(invoice_id: int, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.user_id == user.id).first()
    if not inv or inv.status == "paid":
        return {"ok": False}
    inv.tx_hash = body.get("tx_hash")
    inv.status = "paid"
    inv.paid_at = datetime.utcnow()
    db.query(UserSubscription).filter(UserSubscription.user_id == user.id).update({"status": "expired"})
    db.add(UserSubscription(user_id=user.id, plan_code=inv.plan_code or "pro", status="active", expires_at=datetime.utcnow() + timedelta(days=30)))
    notify_user(db, user.id, "Payment Confirmed", f"Invoice #{inv.id} paid. Plan activated.", "billing")
    db.commit()
    return {"ok": True}


@router.get("/invoices")
def list_invoices(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Invoice).filter(Invoice.user_id == user.id).order_by(Invoice.created_at.desc()).limit(50).all()
    return [{"id": i.id, "plan_code": i.plan_code, "amount": i.amount, "currency": i.currency, "status": i.status, "payment_method": i.payment_method, "tx_hash": i.tx_hash, "created_at": i.created_at.isoformat(), "paid_at": i.paid_at.isoformat() if i.paid_at else None} for i in rows]
