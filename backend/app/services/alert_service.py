import json
import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import AdminAlert, User
from app.services.dingtalk_notify import push_trading_alert, push_system_alert

logger = logging.getLogger(__name__)
settings = get_settings()

# 关键事件才推送钉钉（info 级 OPEN/TRAIL 仅入库，避免刷屏）
DINGTALK_INFO_TYPES = frozenset({
    "STARTUP", "SYSTEM_RESTART", "DEPLOY_READY",
})
DINGTALK_SKIP_INFO_TYPES = frozenset({"OPEN", "TRAIL"})


def _should_push_dingtalk(severity: str, alert_type: str) -> bool:
    if severity in ("critical", "warning"):
        return True
    if alert_type in DINGTALK_SKIP_INFO_TYPES:
        return False
    if alert_type in DINGTALK_INFO_TYPES:
        return True
    if alert_type.startswith("SYSTEM_"):
        return True
    return False


def notify_admin(
    user_id: int,
    severity: str,
    alert_type: str,
    title: str,
    message: str,
    detail: dict | None = None,
) -> None:
    """交易异常仅推送管理员钉钉；客户不接收任何推送。"""
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        uid = user.uid if user else str(user_id)
        display = user.nickname or user.email or user.phone or uid if user else uid

        alert = AdminAlert(
            user_id=user_id,
            severity=severity,
            alert_type=alert_type,
            title=title,
            message=message,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
        db.add(alert)
        db.commit()

        log_line = f"[Alert][{alert_type}] User {user_id}({uid}) {title}: {message}"
        if severity == "critical":
            logger.warning(log_line)
        else:
            logger.info(log_line)

        if _should_push_dingtalk(severity, alert_type):
            push_trading_alert(user_id, uid, display, alert_type, severity, title, message, detail)
    except Exception as e:
        logger.error("notify_admin failed user=%s: %s", user_id, e)
        db.rollback()
    finally:
        db.close()


def notify_system(
    severity: str,
    alert_type: str,
    title: str,
    message: str,
    detail: dict | None = None,
) -> None:
    """系统级告警：重启、部署、全局异常。仅管理员钉钉。"""
    db: Session = SessionLocal()
    try:
        alert = AdminAlert(
            user_id=None,
            severity=severity,
            alert_type=alert_type,
            title=title,
            message=message,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
        db.add(alert)
        db.commit()

        log_line = f"[SystemAlert][{alert_type}] {title}: {message}"
        if severity == "critical":
            logger.warning(log_line)
        else:
            logger.info(log_line)

        if _should_push_dingtalk(severity, alert_type):
            push_system_alert(alert_type, severity, title, message, detail)
    except Exception as e:
        logger.error("notify_system failed: %s", e)
        db.rollback()
    finally:
        db.close()


def list_alerts(db: Session, unread_only: bool = False, limit: int = 100) -> list[AdminAlert]:
    q = db.query(AdminAlert).order_by(AdminAlert.created_at.desc())
    if unread_only:
        q = q.filter(AdminAlert.is_read == False)
    return q.limit(limit).all()


def mark_alert_read(db: Session, alert_id: int) -> bool:
    alert = db.query(AdminAlert).filter(AdminAlert.id == alert_id).first()
    if not alert:
        return False
    alert.is_read = True
    db.commit()
    return True


def mark_all_read(db: Session) -> int:
    count = db.query(AdminAlert).filter(AdminAlert.is_read == False).update({"is_read": True})
    db.commit()
    return count
