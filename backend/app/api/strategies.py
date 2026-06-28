import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.models.platform import Strategy, StrategyVersion
from app.api.deps import get_current_user
from app.services.audit import log_audit
from app.i18n.errors import raise_i18n

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _out(s: Strategy) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description or "",
        "strategy_type": s.strategy_type,
        "config_json": s.config_json or "{}",
        "status": s.status,
        "webhook_token": s.webhook_token,
        "sharpe": s.sharpe,
        "profit_factor": s.profit_factor,
        "max_drawdown": s.max_drawdown,
        "win_rate": s.win_rate,
        "total_pnl": s.total_pnl,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.get("")
def list_strategies(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Strategy).filter(Strategy.user_id == user.id).order_by(Strategy.created_at.desc()).all()
    return [_out(s) for s in rows]


@router.post("")
def create_strategy(body: dict, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = (body.get("name") or "").strip()
    if not name:
        raise_i18n(400, "validation_error")
    s = Strategy(
        user_id=user.id,
        name=name,
        description=body.get("description") or "",
        strategy_type=body.get("strategy_type") or "trend",
        config_json=json.dumps(body.get("config") or {}),
        webhook_token=secrets.token_hex(16),
        status=body.get("status") or "active",
    )
    db.add(s)
    db.flush()
    db.add(StrategyVersion(strategy_id=s.id, version=1, config_json=s.config_json, change_note="Initial"))
    db.commit()
    db.refresh(s)
    log_audit(db, "strategy.create", user_id=user.id, resource_type="strategy", resource_id=s.id, request=request)
    return _out(s)


@router.patch("/{strategy_id}")
def update_strategy(strategy_id: int, body: dict, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == strategy_id, Strategy.user_id == user.id).first()
    if not s:
        raise HTTPException(404)
    if "name" in body:
        s.name = body["name"]
    if "description" in body:
        s.description = body["description"]
    if "status" in body:
        s.status = body["status"]
    if "config" in body:
        s.config_json = json.dumps(body["config"])
        last_v = db.query(StrategyVersion).filter(StrategyVersion.strategy_id == s.id).count()
        db.add(StrategyVersion(strategy_id=s.id, version=last_v + 1, config_json=s.config_json, change_note=body.get("change_note") or "Update"))
    s.updated_at = datetime.utcnow()
    db.commit()
    log_audit(db, "strategy.update", user_id=user.id, resource_type="strategy", resource_id=s.id, request=request)
    return _out(s)


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == strategy_id, Strategy.user_id == user.id).first()
    if not s:
        raise HTTPException(404)
    db.delete(s)
    db.commit()
    log_audit(db, "strategy.delete", user_id=user.id, resource_type="strategy", resource_id=strategy_id, request=request)
    return {"ok": True}


@router.get("/{strategy_id}/versions")
def strategy_versions(strategy_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.query(Strategy).filter(Strategy.id == strategy_id, Strategy.user_id == user.id).first()
    if not s:
        raise HTTPException(404)
    rows = db.query(StrategyVersion).filter(StrategyVersion.strategy_id == s.id).order_by(StrategyVersion.version.desc()).all()
    return [{"id": v.id, "version": v.version, "config_json": v.config_json, "change_note": v.change_note, "created_at": v.created_at.isoformat()} for v in rows]
