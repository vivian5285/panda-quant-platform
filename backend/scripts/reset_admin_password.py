#!/usr/bin/env python3
"""重置管理员密码为 backend/.env 中的 ADMIN_PASSWORD。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings
from app.database import SessionLocal
from app.models import User
from app.utils.auth import hash_password

settings = get_settings()
db = SessionLocal()
try:
    admin = db.query(User).filter(User.email == settings.ADMIN_EMAIL).first()
    if not admin:
        print(f"[FAIL] 未找到管理员 {settings.ADMIN_EMAIL}")
        sys.exit(1)
    admin.password_hash = hash_password(settings.ADMIN_PASSWORD)
    db.commit()
    print(f"[OK] 管理员 {settings.ADMIN_EMAIL} 密码已重置为 .env ADMIN_PASSWORD")
finally:
    db.close()
