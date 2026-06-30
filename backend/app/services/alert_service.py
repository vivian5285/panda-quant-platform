import json
import logging

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services.dingtalk_notify import push_system_alert

logger = logging.getLogger(__name__)

# 仅平台级事件推送钉钉（重启、初始化失败、全局调度异常等）
SYSTEM_DINGTALK_TYPES = frozenset({
    "SYSTEM_RESTART",
    "SYSTEM_INIT_FAIL",
    "DISPATCH_EMPTY",
    "DISPATCH_PARTIAL_FAIL",
    "DEPLOY_READY",
    "SETTLEMENT_APPEAL",
})


def _should_push_system_dingtalk(severity: str, alert_type: str) -> bool:
    if alert_type in SYSTEM_DINGTALK_TYPES:
        return True
    if alert_type.startswith("SYSTEM_"):
        return severity in ("critical", "warning", "info")
    return False


def notify_admin(
    user_id: int,
    severity: str,
    alert_type: str,
    title: str,
    message: str,
    detail: dict | None = None,
) -> None:
    """用户账户状态仅写入 TradeLog（由 TradeLogger 负责），不推送钉钉、不入 admin_alerts。"""
    log_line = f"[UserEvent][{alert_type}] user={user_id} {title}: {message}"
    if severity == "critical":
        logger.warning(log_line)
    elif severity == "warning":
        logger.warning(log_line)
    else:
        logger.info(log_line)
    if detail:
        logger.debug("[UserEvent][%s] detail=%s", alert_type, detail)


def notify_system(
    severity: str,
    alert_type: str,
    title: str,
    message: str,
    detail: dict | None = None,
) -> None:
    """平台重启与全局异常：入库 admin_alerts 并推送管理员钉钉。"""
    from app.models import AdminAlert

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

        if _should_push_system_dingtalk(severity, alert_type):
            push_system_alert(alert_type, severity, title, message, detail)
    except Exception as e:
        logger.error("notify_system failed: %s", e)
        db.rollback()
    finally:
        db.close()


def list_alerts(db: Session, unread_only: bool = False, limit: int = 100, system_only: bool = True) -> list:
    from app.models import AdminAlert

    q = db.query(AdminAlert).order_by(AdminAlert.created_at.desc())
    if system_only:
        q = q.filter(AdminAlert.user_id.is_(None))
    if unread_only:
        q = q.filter(AdminAlert.is_read == False)
    return q.limit(limit).all()


def mark_alert_read(db: Session, alert_id: int) -> bool:
    from app.models import AdminAlert

    alert = db.query(AdminAlert).filter(AdminAlert.id == alert_id).first()
    if not alert:
        return False
    alert.is_read = True
    db.commit()
    return True


def mark_all_read(db: Session, system_only: bool = True) -> int:
    from app.models import AdminAlert

    q = db.query(AdminAlert).filter(AdminAlert.is_read == False)
    if system_only:
        q = q.filter(AdminAlert.user_id.is_(None))
    count = q.update({"is_read": True})
    db.commit()
    return count
