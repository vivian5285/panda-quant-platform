"""Referral code branding: GEMINI canonical form + legacy PANDA alias lookup."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import User

LEGACY_PREFIX = "PANDA-"
CANONICAL_PREFIX = "GEMINI-"


def canonical_referral_code(code: str | None) -> str:
    if not code:
        return ""
    code = code.strip().upper()
    if code.startswith(LEGACY_PREFIX):
        return CANONICAL_PREFIX + code[len(LEGACY_PREFIX):]
    return code


def resolve_referral_user(db: Session, code: str | None) -> User | None:
    """Find referrer by GEMINI- or legacy PANDA- code."""
    if not code or not str(code).strip():
        return None
    raw = str(code).strip().upper()
    user = db.query(User).filter(User.referral_code == raw).first()
    if user:
        return user
    if raw.startswith(CANONICAL_PREFIX):
        legacy = LEGACY_PREFIX + raw[len(CANONICAL_PREFIX):]
        return db.query(User).filter(User.referral_code == legacy).first()
    return None
