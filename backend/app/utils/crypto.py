import base64
import hashlib
from cryptography.fernet import Fernet
from app.config import get_settings


def _get_fernet() -> Fernet:
    key = get_settings().ENCRYPTION_KEY.encode()
    digest = hashlib.sha256(key).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_text(plain: str) -> str:
    if not plain:
        return ""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_text(cipher: str) -> str:
    if not cipher:
        return ""
    return _get_fernet().decrypt(cipher.encode()).decode()
