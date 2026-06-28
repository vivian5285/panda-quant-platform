import hashlib
import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.models.platform import UserPreference, UserOpenApiKey
from app.api.deps import get_current_user
from app.services.totp import generate_totp_secret, totp_provisioning_uri, verify_totp
from app.services.audit import log_audit
from app.services.user_lookup import display_name
from app.i18n.errors import raise_i18n

router = APIRouter(prefix="/settings", tags=["settings"])


def _pref(db: Session, user_id: int) -> UserPreference:
    p = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
    if not p:
        p = UserPreference(user_id=user_id)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


@router.get("")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _pref(db, user.id)
    return {
        "notify_email": p.notify_email,
        "notify_in_app": p.notify_in_app,
        "notify_telegram": p.notify_telegram,
        "notify_webhook": p.notify_webhook,
        "telegram_chat_id": p.telegram_chat_id,
        "discord_webhook_url": p.discord_webhook_url or "",
        "custom_webhook_url": p.custom_webhook_url or "",
        "totp_enabled": p.totp_enabled,
        "avatar_url": p.avatar_url or "",
        "display_name": display_name(user),
    }


@router.patch("")
def update_settings(body: dict, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _pref(db, user.id)
    for key in ("notify_email", "notify_in_app", "notify_telegram", "notify_webhook", "telegram_chat_id", "discord_webhook_url", "custom_webhook_url", "avatar_url"):
        if key in body:
            setattr(p, key, body[key])
    db.commit()
    log_audit(db, "settings.update", user_id=user.id, request=request)
    return {"ok": True}


@router.post("/totp/setup")
def totp_setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _pref(db, user.id)
    if not p.totp_secret:
        p.totp_secret = generate_totp_secret()
        db.commit()
    uri = totp_provisioning_uri(p.totp_secret, user.email or user.phone or user.uid or "user")
    return {"secret": p.totp_secret, "provisioning_uri": uri, "enabled": p.totp_enabled}


@router.post("/totp/enable")
def totp_enable(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _pref(db, user.id)
    if not p.totp_secret or not verify_totp(p.totp_secret, body.get("code", "")):
        raise_i18n(400, "code_error")
    p.totp_enabled = True
    db.commit()
    return {"ok": True, "enabled": True}


@router.post("/totp/disable")
def totp_disable(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p = _pref(db, user.id)
    if p.totp_enabled and not verify_totp(p.totp_secret or "", body.get("code", "")):
        raise_i18n(400, "code_error")
    p.totp_enabled = False
    db.commit()
    return {"ok": True}


@router.get("/api-keys")
def list_api_keys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(UserOpenApiKey).filter(UserOpenApiKey.user_id == user.id).order_by(UserOpenApiKey.created_at.desc()).all()
    return [{"id": k.id, "name": k.name, "key_prefix": k.key_prefix, "permissions": k.permissions, "is_active": k.is_active, "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None, "created_at": k.created_at.isoformat()} for k in rows]


@router.post("/api-keys")
def create_api_key(body: dict, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    raw = f"pk_{secrets.token_urlsafe(32)}"
    prefix = raw[:10]
    k = UserOpenApiKey(
        user_id=user.id,
        name=body.get("name") or "API Key",
        key_prefix=prefix,
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        permissions=body.get("permissions") or "read",
    )
    db.add(k)
    db.commit()
    log_audit(db, "api_key.create", user_id=user.id, resource_type="api_key", resource_id=k.id, request=request)
    return {"id": k.id, "key": raw, "prefix": prefix, "message": "Save this key — it won't be shown again."}


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: int, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    k = db.query(UserOpenApiKey).filter(UserOpenApiKey.id == key_id, UserOpenApiKey.user_id == user.id).first()
    if k:
        k.is_active = False
        db.commit()
        log_audit(db, "api_key.revoke", user_id=user.id, resource_type="api_key", resource_id=key_id, request=request)
    return {"ok": True}
