"""Daily friendly reminders for unpaid performance fees (email + in-app)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Settlement, User, PaymentStatus
from app.services.notification import notify_user
from app.services.settlement import get_pending_settlement

logger = logging.getLogger(__name__)
settings = get_settings()


def _send_reminder_email(user: User, payable: float, settlement_id: int) -> bool:
    if not user.email:
        return False
    if settings.EMAIL_DEV_MODE:
        logger.info(
            "[SETTLEMENT REMINDER DEV] user=%s email=%s payable=%.2f settlement=%s",
            user.id, user.email, payable, settlement_id,
        )
        return True
    if not settings.SMTP_HOST:
        logger.warning("[SETTLEMENT REMINDER] SMTP not configured for user %s", user.id)
        return False

    import smtplib
    from email.mime.text import MIMEText

    subject = "双子星AI量化 · 绩效服务费缴纳提醒"
    body = (
        f"您好，\n\n"
        f"您的 AI 绩效服务费账单 #{settlement_id} 待缴纳，应付金额：{payable:.2f} USDT。\n\n"
        f"请登录平台「绩效结算」页面，向您的专属 USDT 子地址转账对应金额；"
        f"系统将通过 RPC 自动追踪到账，确认后 AI 实盘将恢复，推广奖励亦将同步结算。\n\n"
        f"如有疑问，请联系客服。\n\n"
        f"— {settings.SMTP_FROM}"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = user.email
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_TLS:
                server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, [user.email], msg.as_string())
        return True
    except Exception as e:
        logger.warning("settlement reminder email failed user=%s: %s", user.id, e)
        return False


def _already_reminded_today(db: Session, user_id: int) -> bool:
    from app.models.platform import UserNotification

    today = date.today()
    row = (
        db.query(UserNotification)
        .filter(
            UserNotification.user_id == user_id,
            UserNotification.category == "settlement_reminder_daily",
            UserNotification.created_at >= datetime.combine(today, datetime.min.time()),
        )
        .first()
    )
    return row is not None


def send_daily_settlement_reminders(db: Session) -> dict:
    """Send at most one reminder per user per day while bill is pending/paid."""
    stats = {"checked": 0, "notified": 0, "emailed": 0, "skipped": 0}
    rows = (
        db.query(Settlement)
        .filter(Settlement.payment_status.in_((PaymentStatus.PENDING.value, PaymentStatus.PAID.value)))
        .all()
    )
    seen_users: set[int] = set()
    for settlement in rows:
        uid = settlement.user_id
        if uid in seen_users:
            continue
        seen_users.add(uid)
        stats["checked"] += 1
        user = db.query(User).filter(User.id == uid).first()
        if not user or not user.is_active:
            stats["skipped"] += 1
            continue
        if _already_reminded_today(db, uid):
            stats["skipped"] += 1
            continue

        payable = float(settlement.user_payable or 0)
        title = "绩效服务费缴纳提醒"
        message = (
            f"账单 #{settlement.id} 待缴纳 {payable:.2f} USDT。"
            f"请前往「绩效结算」向专属地址转账，到账后 AI 将自动恢复。"
        )
        notify_user(db, uid, title, message, category="settlement_reminder_daily")
        stats["notified"] += 1
        if _send_reminder_email(user, payable, settlement.id):
            stats["emailed"] += 1

    return stats
