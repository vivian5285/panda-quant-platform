import asyncio
import json
import os
import platform
import time

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import User, Trade
from app.models.platform import AuditLog, LoginRecord, RiskAlert, STAFF_ROLES
from app.api.deps import get_admin_user, get_staff_user
from app.services.dispatcher import supervisor_pool
from app.services.redis_client import get_redis

router = APIRouter(prefix="/admin/system", tags=["admin-system"])


@router.get("/monitor")
def system_monitor(admin=Depends(get_admin_user)):
    redis_ok = get_redis() is not None
    return {
        "hostname": platform.node(),
        "python": platform.python_version(),
        "active_supervisors": len(supervisor_pool.get_all()),
        "redis_connected": redis_ok,
        "uptime_hint": "99.99%",
        "api_latency_ms": 12,
        "binance_connections": len(supervisor_pool.get_all()),
        "websocket_status": "active",
    }


@router.get("/audit-logs")
def audit_logs(limit: int = 100, admin=Depends(get_staff_user), db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500)).all()
    return [{"id": r.id, "user_id": r.user_id, "actor_id": r.actor_id, "action": r.action, "resource_type": r.resource_type, "resource_id": r.resource_id, "ip_address": r.ip_address, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/login-records")
def login_records(limit: int = 100, admin=Depends(get_staff_user), db: Session = Depends(get_db)):
    rows = db.query(LoginRecord).order_by(LoginRecord.created_at.desc()).limit(min(limit, 500)).all()
    return [{"id": r.id, "user_id": r.user_id, "ip_address": r.ip_address, "user_agent": r.user_agent, "success": r.success, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/risk-alerts")
def risk_alerts(unresolved_only: bool = True, admin=Depends(get_staff_user), db: Session = Depends(get_db)):
    q = db.query(RiskAlert)
    if unresolved_only:
        q = q.filter(RiskAlert.is_resolved == False)
    rows = q.order_by(RiskAlert.created_at.desc()).limit(100).all()
    return [{"id": r.id, "user_id": r.user_id, "alert_type": r.alert_type, "severity": r.severity, "message": r.message, "is_resolved": r.is_resolved, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/orders")
def all_orders(limit: int = 100, admin=Depends(get_staff_user), db: Session = Depends(get_db)):
    rows = db.query(Trade).order_by(Trade.created_at.desc()).limit(min(limit, 500)).all()
    return [{"id": t.id, "user_id": t.user_id, "symbol": t.symbol, "side": t.side, "realized_pnl": t.realized_pnl, "status": t.status, "created_at": t.created_at.isoformat()} for t in rows]


@router.get("/online")
def online_stats(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    from datetime import datetime, timedelta
    since = datetime.utcnow() - timedelta(minutes=15)
    recent = db.query(LoginRecord).filter(LoginRecord.created_at >= since, LoginRecord.success == True).count()
    return {"recent_logins_15m": recent, "active_supervisors": len(supervisor_pool.get_all())}


ws_router = APIRouter()


@ws_router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    from app.utils.auth import decode_access_token
    from app.services.analytics import build_user_analytics
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    payload = decode_access_token(token)
    if not payload:
        await websocket.close(code=4401)
        return
    user_id = int(payload.get("sub"))
    await websocket.accept()
    try:
        while True:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    analytics = build_user_analytics(db, user.id, 30)
                    await websocket.send_json({"type": "tick", "analytics": analytics, "ts": time.time()})
            finally:
                db.close()
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
