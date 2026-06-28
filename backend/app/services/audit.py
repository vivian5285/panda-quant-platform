import json
from fastapi import Request
from sqlalchemy.orm import Session
from app.models.platform import AuditLog


def log_audit(
    db: Session,
    action: str,
    *,
    user_id: int | None = None,
    actor_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: dict | None = None,
    request: Request | None = None,
):
    ip = None
    if request and request.client:
        ip = request.client.host
    db.add(AuditLog(
        user_id=user_id,
        actor_id=actor_id or user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        detail_json=json.dumps(detail or {}, ensure_ascii=False),
        ip_address=ip,
    ))
    db.commit()
