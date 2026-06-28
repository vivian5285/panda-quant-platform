import secrets
import string
from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


def generate_referral_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "PANDA-" + "".join(secrets.choice(chars) for _ in range(length))


def generate_uid(db, length: int = 8) -> str:
    """Generate unique numeric UID, e.g. 88472931."""
    for _ in range(100):
        uid = "".join(secrets.choice(string.digits) for _ in range(length))
        if uid[0] != "0":
            from app.models import User
            if not db.query(User).filter(User.uid == uid).first():
                return uid
    raise RuntimeError("Failed to generate unique UID")


def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    return phone


def normalize_account(account: str) -> str:
    account = account.strip()
    if "@" in account:
        return account.lower()
    if account.replace("+", "").isdigit():
        return normalize_phone(account)
    return account
