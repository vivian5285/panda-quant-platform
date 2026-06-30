import logging
import random
import string
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import VerificationCode, User
from app.utils.auth import normalize_phone

logger = logging.getLogger(__name__)
settings = get_settings()

PURPOSES = frozenset({"login", "register", "security"})


def _generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def _check_send_interval(db: Session, channel: str, target: str) -> None:
    recent = db.query(VerificationCode).filter(
        VerificationCode.channel == channel,
        VerificationCode.target == target,
        VerificationCode.created_at > datetime.utcnow() - timedelta(seconds=settings.SMS_SEND_INTERVAL_SECONDS),
    ).first()
    if recent:
        raise ValueError(f"请等待 {settings.SMS_SEND_INTERVAL_SECONDS} 秒后再获取")


def _dispatch_phone(phone: str, code: str, purpose: str) -> None:
    if settings.SMS_DEV_MODE:
        logger.info("[SMS DEV] phone=%s purpose=%s code=%s", phone, purpose, code)
        return
    from app.services.sms import _dispatch_sms
    _dispatch_sms(phone, code)


def _dispatch_email(email: str, code: str, purpose: str) -> None:
    if settings.EMAIL_DEV_MODE:
        logger.info("[EMAIL DEV] email=%s purpose=%s code=%s", email, purpose, code)
        return
    if settings.SMTP_HOST:
        _send_smtp_email(email, code, purpose)
        return
    logger.warning("[EMAIL] SMTP 未配置，验证码: %s -> %s", email, code)


def _send_smtp_email(email: str, code: str, purpose: str) -> None:
    import smtplib
    from email.mime.text import MIMEText

    subject = "双子星AI量化 · GEMINI AI 验证码"
    body = f"您的验证码是 {code}，{settings.SMS_CODE_EXPIRE_MINUTES} 分钟内有效。用途：{purpose}"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = email
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        if settings.SMTP_TLS:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [email], msg.as_string())


def send_code(db: Session, channel: str, target: str, purpose: str, user_id: int | None = None) -> dict:
    channel = channel.lower()
    purpose = purpose.lower()
    if channel not in ("phone", "email"):
        raise ValueError("Invalid channel")
    if purpose not in PURPOSES:
        raise ValueError("Invalid purpose")

    if channel == "phone":
        target = normalize_phone(target)
        if len(target) < 6:
            raise ValueError("Invalid phone number")
    else:
        target = target.strip().lower()

    if purpose == "login":
        if channel == "phone":
            user = db.query(User).filter(User.phone == target).first()
        else:
            user = db.query(User).filter(User.email == target).first()
        if not user:
            raise ValueError("账号未注册")
    elif purpose == "register":
        if channel == "phone":
            if db.query(User).filter(User.phone == target).first():
                raise ValueError("手机号已注册")
        else:
            if db.query(User).filter(User.email == target).first():
                raise ValueError("邮箱已注册")
    elif purpose == "security":
        if not user_id:
            raise ValueError("安全验证码需登录后获取")

    _check_send_interval(db, channel, target)
    code = _generate_code()
    expires = datetime.utcnow() + timedelta(minutes=settings.SMS_CODE_EXPIRE_MINUTES)
    db.add(VerificationCode(
        channel=channel,
        target=target,
        code=code,
        purpose=purpose,
        user_id=user_id,
        expires_at=expires,
    ))
    db.commit()

    if channel == "phone":
        _dispatch_phone(target, code, purpose)
    else:
        _dispatch_email(target, code, purpose)

    result = {"message": "验证码已发送", "expires_in": settings.SMS_CODE_EXPIRE_MINUTES * 60}
    if settings.SMS_DEV_MODE and channel == "phone":
        result["dev_code"] = code
    if settings.EMAIL_DEV_MODE and channel == "email":
        result["dev_code"] = code
    return result


def verify_code(
    db: Session,
    channel: str,
    target: str,
    code: str,
    purpose: str,
    consume: bool = True,
) -> bool:
    channel = channel.lower()
    purpose = purpose.lower()
    if channel == "phone":
        target = normalize_phone(target)
    else:
        target = target.strip().lower()

    record = db.query(VerificationCode).filter(
        VerificationCode.channel == channel,
        VerificationCode.target == target,
        VerificationCode.purpose == purpose,
        VerificationCode.used == False,
        VerificationCode.code == code.strip(),
        VerificationCode.expires_at > datetime.utcnow(),
    ).order_by(VerificationCode.created_at.desc()).first()

    if not record:
        raise ValueError("验证码错误或已过期")

    if consume:
        record.used = True
        db.commit()
    return True


def verify_login_code(db: Session, channel: str, target: str, code: str) -> User:
    verify_code(db, channel, target, code, "login")
    if channel == "phone":
        target = normalize_phone(target)
        user = db.query(User).filter(User.phone == target).first()
    else:
        user = db.query(User).filter(User.email == target.strip().lower()).first()
    if not user:
        raise ValueError("用户不存在")
    return user


def verify_register_code(db: Session, channel: str, target: str, code: str) -> None:
    verify_code(db, channel, target, code, "register")


def require_email_contact(user: User) -> None:
    if not user.email:
        raise ValueError("请先在个人资料中绑定邮箱")


def verify_security_email(db: Session, user: User, email_code: str) -> None:
    require_email_contact(user)
    verify_code(db, "email", user.email, email_code, "security")


def send_security_email_code(db: Session, user: User) -> dict:
    require_email_contact(user)
    return send_code(db, "email", user.email, "security", user_id=user.id)


def require_both_contacts(user: User) -> None:
    """Legacy alias — email-only security verification."""
    require_email_contact(user)


def verify_security_dual(db: Session, user: User, email_code: str, phone_code: str = "") -> None:
    """Email verification only (phone_code ignored)."""
    verify_security_email(db, user, email_code)


def send_security_dual_codes(db: Session, user: User) -> dict:
    res = send_security_email_code(db, user)
    out = {"message": "安全验证码已发送至邮箱", "expires_in": res["expires_in"]}
    if settings.EMAIL_DEV_MODE:
        out["dev_email_code"] = res.get("dev_code")
    return out
