import logging
import random
import string
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import SmsVerificationCode, User
from app.utils.auth import normalize_phone
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _generate_code(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def send_login_code(db: Session, phone: str) -> dict:
    phone = normalize_phone(phone)
    if len(phone) < 6:
        raise ValueError("Invalid phone number")

    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise ValueError("Phone not registered")

    code = _generate_code()
    expires = datetime.utcnow() + timedelta(minutes=settings.SMS_CODE_EXPIRE_MINUTES)

    db.add(SmsVerificationCode(
        phone=phone,
        code=code,
        purpose="login",
        expires_at=expires,
    ))
    db.commit()

    result = {"message": "Verification code sent", "expires_in": settings.SMS_CODE_EXPIRE_MINUTES * 60}

    if settings.SMS_DEV_MODE:
        logger.info(f"[SMS DEV] phone={phone} code={code}")
        result["dev_code"] = code
    else:
        _dispatch_sms(phone, code)

    return result


def verify_login_code(db: Session, phone: str, code: str) -> User:
    phone = normalize_phone(phone)
    record = db.query(SmsVerificationCode).filter(
        SmsVerificationCode.phone == phone,
        SmsVerificationCode.purpose == "login",
        SmsVerificationCode.used == False,
        SmsVerificationCode.code == code.strip(),
        SmsVerificationCode.expires_at > datetime.utcnow(),
    ).order_by(SmsVerificationCode.created_at.desc()).first()

    if not record:
        raise ValueError("Invalid or expired verification code")

    record.used = True
    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        raise ValueError("User not found")
    db.commit()
    return user


def _dispatch_sms(phone: str, code: str):
    """Production SMS dispatch — plug in Aliyun/Tencent/Twilio via env."""
    if settings.SMS_ALIYUN_ACCESS_KEY and settings.SMS_ALIYUN_SIGN_NAME:
        try:
            _send_aliyun_sms(phone, code)
            return
        except Exception as e:
            logger.error(f"Aliyun SMS failed: {e}")
            raise ValueError("SMS send failed, try again later")
    logger.warning(f"SMS provider not configured, code for {phone}: {code}")


def _send_aliyun_sms(phone: str, code: str):
    import json
    import hmac
    import hashlib
    import base64
    import uuid
    from urllib.parse import quote
    import requests

    params = {
        "AccessKeyId": settings.SMS_ALIYUN_ACCESS_KEY,
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone if phone.startswith("+") else f"+86{phone.lstrip('0')}" if phone.startswith("1") else phone,
        "SignName": settings.SMS_ALIYUN_SIGN_NAME,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": str(uuid.uuid4()),
        "SignatureVersion": "1.0",
        "TemplateCode": settings.SMS_ALIYUN_TEMPLATE_CODE,
        "TemplateParam": json.dumps({"code": code}),
        "Timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": "2017-05-25",
    }
    sorted_params = sorted(params.items())
    query = "&".join(f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in sorted_params)
    string_to_sign = f"GET&{quote('/', safe='')}&{quote(query, safe='')}"
    key = (settings.SMS_ALIYUN_ACCESS_SECRET + "&").encode()
    signature = base64.b64encode(hmac.new(key, string_to_sign.encode(), hashlib.sha1).digest()).decode()
    params["Signature"] = signature

    resp = requests.get("https://dysmsapi.aliyuncs.com/", params=params, timeout=10)
    data = resp.json()
    if data.get("Code") != "OK":
        raise RuntimeError(data.get("Message", "Aliyun SMS error"))
