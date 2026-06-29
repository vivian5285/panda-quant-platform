"""Persist per-user signal dispatch execution results."""
from __future__ import annotations

import json
from sqlalchemy.orm import Session

from app.models import User
from app.models.platform import SignalDispatchLog, SignalDispatchUserResult


def user_result_to_dict(row: SignalDispatchUserResult, user: User | None = None) -> dict:
    detail = {}
    if row.detail_json:
        try:
            detail = json.loads(row.detail_json)
        except json.JSONDecodeError:
            detail = {}
    return {
        "id": row.id,
        "dispatch_log_id": row.dispatch_log_id,
        "user_id": row.user_id,
        "user_uid": row.user_uid or (user.uid if user else None),
        "user_email": user.email if user else None,
        "user_nickname": user.nickname if user else None,
        "status": row.status,
        "reason": row.reason,
        "error_message": row.error_message,
        "slippage": row.slippage,
        "trade_id": row.trade_id,
        "latency_ms": row.latency_ms,
        "detail": detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def save_dispatch_user_results(db: Session, dispatch_log_id: int, results: list[dict]) -> None:
    if not results:
        return
    user_ids = [r["user_id"] for r in results if r.get("user_id")]
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    for item in results:
        uid = item.get("user_id")
        if not uid:
            continue
        user = users.get(uid)
        detail = item.get("detail") or {}
        if not isinstance(detail, dict):
            detail = {}
        db.add(
            SignalDispatchUserResult(
                dispatch_log_id=dispatch_log_id,
                user_id=uid,
                user_uid=user.uid if user else item.get("user_uid"),
                status=item.get("status", "error"),
                reason=item.get("reason"),
                error_message=item.get("message") or item.get("error_message"),
                slippage=item.get("slippage"),
                trade_id=item.get("trade_id"),
                latency_ms=item.get("latency_ms"),
                detail_json=json.dumps(detail, ensure_ascii=False),
            )
        )
    db.commit()


def finalize_dispatch_log(db: Session, row: SignalDispatchLog, results: list[dict], *, status: str | None = None) -> SignalDispatchLog:
    ok = sum(1 for r in results if r.get("status") == "ok")
    errors = sum(1 for r in results if r.get("status") == "error")
    skipped = sum(1 for r in results if r.get("status") in ("skipped", "risk_blocked"))
    row.dispatched_count = ok
    row.error_count = errors
    row.skipped_count = skipped
    if status:
        row.status = status
    elif errors and ok:
        row.status = "partial"
    elif errors:
        row.status = "error"
    elif skipped and not ok:
        row.status = "skipped"
    else:
        row.status = "ok"
    db.commit()
    db.refresh(row)
    return row


def list_dispatch_user_results(db: Session, dispatch_log_id: int) -> list[dict]:
    rows = (
        db.query(SignalDispatchUserResult, User)
        .outerjoin(User, User.id == SignalDispatchUserResult.user_id)
        .filter(SignalDispatchUserResult.dispatch_log_id == dispatch_log_id)
        .order_by(SignalDispatchUserResult.created_at.asc())
        .all()
    )
    return [user_result_to_dict(r, u) for r, u in rows]
