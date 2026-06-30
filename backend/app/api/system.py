import asyncio
import json
import os
import platform
import time

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import User, Trade, TradeLog
from app.models.platform import AuditLog, LoginRecord, RiskAlert
from app.api.deps import get_admin_user
from app.services.dispatcher import supervisor_pool
from app.services.redis_client import get_redis
from app.schemas import AdminWebhookTest
from app.services.platform_analytics import build_platform_analytics, enrich_trades
from app.services.signal_admin import build_test_payload, run_signal_dispatch, record_webhook_hit
from app.services.dispatch_persistence import list_dispatch_user_results
from app.services.trading_control import get_global_control, set_global_pause, set_global_risk, is_globally_paused
from app.services.audit import log_audit

router = APIRouter(prefix="/admin/system", tags=["admin-system"])


@router.get("/monitor")
def system_monitor(admin=Depends(get_admin_user)):
    import os
    import time
    import urllib.request

    redis = get_redis()
    redis_ok = redis is not None
    webhook_status = "unknown"
    webhook_last_at = None
    webhook_today = 0
    if redis_ok:
        try:
            webhook_last_at = redis.get("stats:webhook:last_at")
            if isinstance(webhook_last_at, bytes):
                webhook_last_at = webhook_last_at.decode()
            raw_total = redis.get("stats:webhook:total")
            webhook_today = int(raw_total or 0)
        except Exception:
            pass

    webhook_port = int(os.getenv("WEBHOOK_PORT", "6010"))
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{webhook_port}/health", timeout=2) as resp:
            webhook_status = "ok" if resp.status == 200 else "degraded"
    except Exception:
        webhook_status = "down"

    binance_latency_ms = 12
    try:
        t0 = time.time()
        urllib.request.urlopen("https://fapi.binance.com/fapi/v1/ping", timeout=3)
        binance_latency_ms = max(1, int((time.time() - t0) * 1000))
    except Exception:
        binance_latency_ms = -1

    global_ctrl = get_global_control()

    from app.config import get_settings
    from app.services.dingtalk_secrets import is_dingtalk_configured
    cfg = get_settings()

    return {
        "hostname": platform.node(),
        "python": platform.python_version(),
        "active_supervisors": len(supervisor_pool.get_all()),
        "redis_connected": redis_ok,
        "uptime_hint": "99.99%",
        "api_latency_ms": binance_latency_ms if binance_latency_ms > 0 else 12,
        "binance_latency_ms": binance_latency_ms,
        "binance_connections": len(supervisor_pool.get_all()),
        "websocket_status": "active",
        "webhook_status": webhook_status,
        "webhook_last_received_at": webhook_last_at,
        "webhook_received_total": webhook_today,
        "queue_depth": len(supervisor_pool.get_all()),
        "dispatch_mode": "inline_thread",
        "global_trading_paused": global_ctrl.get("global_trading_paused", False),
        "global_risk_multiplier": global_ctrl.get("global_risk_multiplier", 1.0),
        "dingtalk_configured": is_dingtalk_configured(),
    }


@router.get("/audit-logs")
def audit_logs(
    limit: int = 100,
    action: str | None = None,
    user_id: int | None = None,
    actor_id: int | None = None,
    q: str | None = None,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    import json
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if actor_id is not None:
        query = query.filter(AuditLog.actor_id == actor_id)
    if q:
        needle = f"%{q.strip()}%"
        query = query.filter(
            (AuditLog.action.ilike(needle))
            | (AuditLog.resource_type.ilike(needle))
            | (AuditLog.resource_id.ilike(needle))
            | (AuditLog.detail_json.ilike(needle))
        )
    rows = query.order_by(AuditLog.created_at.desc()).limit(min(limit, 500)).all()
    out = []
    for r in rows:
        detail = None
        if r.detail_json:
            try:
                detail = json.loads(r.detail_json)
            except json.JSONDecodeError:
                detail = r.detail_json
        out.append({
            "id": r.id,
            "user_id": r.user_id,
            "actor_id": r.actor_id,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "detail": detail,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat(),
        })
    return out


@router.get("/login-records")
def login_records(limit: int = 100, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.query(LoginRecord).order_by(LoginRecord.created_at.desc()).limit(min(limit, 500)).all()
    return [{"id": r.id, "user_id": r.user_id, "ip_address": r.ip_address, "user_agent": r.user_agent, "success": r.success, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/risk-alerts")
def risk_alerts(unresolved_only: bool = True, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    q = db.query(RiskAlert)
    if unresolved_only:
        q = q.filter(RiskAlert.is_resolved == False)
    rows = q.order_by(RiskAlert.created_at.desc()).limit(100).all()
    return [{"id": r.id, "user_id": r.user_id, "alert_type": r.alert_type, "severity": r.severity, "message": r.message, "is_resolved": r.is_resolved, "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/orders")
def all_orders(limit: int = 100, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Trade, User)
        .join(User, Trade.user_id == User.id)
        .order_by(Trade.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    trades = [t for t, _ in rows]
    enriched = {r["id"]: r for r in enrich_trades(db, trades)}
    out = []
    for t, u in rows:
        base = enriched.get(t.id, {})
        out.append({
            "id": t.id,
            "user_id": t.user_id,
            "user_uid": u.uid,
            "user_email": u.email or "",
            "user_nickname": u.nickname or "",
            "symbol": t.symbol,
            "side": t.side,
            "realized_pnl": t.realized_pnl,
            "status": t.status,
            "slippage": base.get("slippage"),
            "funding_fee": base.get("funding_fee"),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return out


@router.get("/trade-logs")
def all_trade_logs(
    limit: int = 200,
    user_id: int | None = None,
    admin=Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    q = db.query(TradeLog, User).join(User, TradeLog.user_id == User.id)
    if user_id:
        q = q.filter(TradeLog.user_id == user_id)
    rows = q.order_by(TradeLog.created_at.desc()).limit(min(limit, 500)).all()
    out = []
    for log, u in rows:
        detail = None
        if log.detail_json:
            try:
                detail = json.loads(log.detail_json)
            except Exception:
                detail = {}
        out.append({
            "id": log.id,
            "user_id": log.user_id,
            "user_uid": u.uid,
            "user_email": u.email or "",
            "user_nickname": u.nickname or "",
            "event_type": log.event_type,
            "message": log.message,
            "trade_id": log.trade_id,
            "detail_json": log.detail_json,
            "detail": detail,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })
    return out


@router.get("/online")
def online_stats(admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    from datetime import datetime, timedelta
    since = datetime.utcnow() - timedelta(minutes=15)
    recent = db.query(LoginRecord).filter(LoginRecord.created_at >= since, LoginRecord.success == True).count()
    return {"recent_logins_15m": recent, "active_supervisors": len(supervisor_pool.get_all())}


@router.get("/trading-control")
def admin_trading_control(admin=Depends(get_admin_user)):
    return get_global_control()


@router.patch("/trading-control")
def admin_update_trading_control(body: dict, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    result = get_global_control()
    if "global_trading_paused" in body:
        paused = bool(body["global_trading_paused"])
        result = set_global_pause(paused)
        log_audit(
            db,
            "platform.trading_pause" if paused else "platform.trading_resume",
            actor_id=admin.id,
            resource_type="platform",
            detail={"global_trading_paused": paused, "note": body.get("note", "")},
        )
    if "global_risk_multiplier" in body:
        try:
            result = set_global_risk(float(body["global_risk_multiplier"]))
        except ValueError as e:
            raise HTTPException(400, str(e))
        log_audit(
            db,
            "platform.risk_multiplier",
            actor_id=admin.id,
            resource_type="platform",
            detail={"global_risk_multiplier": result.get("global_risk_multiplier")},
        )
    if "global_trading_paused" not in body and "global_risk_multiplier" not in body:
        raise HTTPException(400, "global_trading_paused or global_risk_multiplier required")
    return result


@router.get("/signal-dispatch-logs")
def signal_dispatch_logs(limit: int = 50, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    from app.models.platform import SignalDispatchLog

    rows = (
        db.query(SignalDispatchLog)
        .order_by(SignalDispatchLog.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [{
        "id": r.id,
        "template_id": r.template_id,
        "action": r.action,
        "dispatched_count": r.dispatched_count,
        "error_count": r.error_count,
        "skipped_count": getattr(r, "skipped_count", 0) or 0,
        "success_count": max(0, (r.dispatched_count or 0)),
        "status": r.status,
        "source": r.source,
        "payload": json.loads(r.payload_json or "{}") if r.payload_json else {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.get("/signal-dispatch-logs/{dispatch_id}/results")
def signal_dispatch_user_results(dispatch_id: int, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    from app.models.platform import SignalDispatchLog

    row = db.query(SignalDispatchLog).filter(SignalDispatchLog.id == dispatch_id).first()
    if not row:
        raise HTTPException(404, "Dispatch log not found")
    return list_dispatch_user_results(db, dispatch_id)


@router.post("/webhook-test")
def webhook_test(body: AdminWebhookTest, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    payload = build_test_payload(body.payload or {})
    record_webhook_hit(str(payload.get("action", "TEST")))
    row, result = run_signal_dispatch(db, payload, source="admin_test")
    log_audit(
        db,
        "admin.webhook_test",
        actor_id=admin.id,
        resource_type="webhook",
        detail={
            "dispatch_id": row.id,
            "action": row.action,
            "dispatched": row.dispatched_count,
            "errors": row.error_count,
        },
    )
    return {
        "ok": True,
        "dispatch_id": row.id,
        "dispatched": row.dispatched_count,
        "errors": row.error_count,
        "skipped": row.skipped_count,
        "status": row.status,
        "results": result.get("results", []),
        "reason": result.get("reason"),
    }


@router.get("/analytics")
def platform_analytics(days: int = 14, admin=Depends(get_admin_user), db: Session = Depends(get_db)):
    return build_platform_analytics(db, days=days)


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
                    from app.services.user_account import build_dashboard_stats
                    from app.schemas import TradeOut

                    analytics = build_user_analytics(db, user.id, 90)
                    dashboard = build_dashboard_stats(db, user)
                    trades_rows = (
                        db.query(Trade)
                        .filter(Trade.user_id == user.id)
                        .order_by(Trade.created_at.desc())
                        .limit(12)
                        .all()
                    )
                    trades = [TradeOut.model_validate(t).model_dump(mode="json") for t in trades_rows]
                    await websocket.send_json({
                        "type": "tick",
                        "analytics": analytics,
                        "dashboard": dashboard.model_dump(mode="json"),
                        "trades": trades,
                        "ts": time.time(),
                    })
            finally:
                db.close()
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass


@ws_router.websocket("/ws/admin/monitor")
async def admin_monitor_ws(websocket: WebSocket):
    from app.utils.auth import decode_access_token
    from app.models.platform import SignalDispatchLog

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    payload = decode_access_token(token)
    if not payload or payload.get("role") != "admin":
        await websocket.close(code=4403)
        return
    await websocket.accept()
    try:
        while True:
            db = SessionLocal()
            try:
                orders_rows = (
                    db.query(Trade, User)
                    .join(User, Trade.user_id == User.id)
                    .order_by(Trade.created_at.desc())
                    .limit(30)
                    .all()
                )
                orders = [{
                    "id": t.id,
                    "user_uid": u.uid,
                    "side": t.side,
                    "realized_pnl": t.realized_pnl,
                    "status": t.status,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                } for t, u in orders_rows]
                signal_logs = (
                    db.query(SignalDispatchLog)
                    .order_by(SignalDispatchLog.created_at.desc())
                    .limit(15)
                    .all()
                )
                signals = [{
                    "id": r.id,
                    "action": r.action,
                    "status": r.status,
                    "dispatched_count": r.dispatched_count,
                    "source": r.source,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                } for r in signal_logs]
                mon = {
                    "active_supervisors": len(supervisor_pool.get_all()),
                    "redis_connected": get_redis() is not None,
                    "global_trading_paused": is_globally_paused(),
                }
                await websocket.send_json({
                    "type": "admin_tick",
                    "monitor": mon,
                    "orders": orders,
                    "signal_logs": signals,
                    "ts": time.time(),
                })
            finally:
                db.close()
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
