from sqlalchemy.orm import Session
from app.models import User


def find_user_by_identifier(db: Session, identifier: str) -> User | None:
    identifier = identifier.strip()
    if not identifier:
        return None

    user = db.query(User).filter(User.uid == identifier).first()
    if user:
        return user

    if "@" in identifier:
        return db.query(User).filter(User.email == identifier.lower()).first()

    phone = identifier.replace(" ", "").replace("-", "")
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    user = db.query(User).filter(User.phone == phone).first()
    if user:
        return user
    return db.query(User).filter(User.phone == identifier).first()


def display_name(user: User) -> str:
    if user.nickname:
        return user.nickname
    if user.email:
        return user.email.split("@")[0]
    if user.phone:
        return user.phone[-4:].rjust(len(user.phone), "*") if len(user.phone) > 4 else user.phone
    return user.uid or f"User#{user.id}"


def mask_user_public(user: User) -> dict:
    email_mask = None
    if user.email:
        parts = user.email.split("@")
        email_mask = parts[0][:2] + "***@" + parts[1] if len(parts) == 2 else user.email
    phone_mask = None
    if user.phone:
        phone_mask = user.phone[:3] + "****" + user.phone[-4:] if len(user.phone) >= 7 else "****"
    return {
        "uid": user.uid,
        "nickname": user.nickname,
        "display_name": display_name(user),
        "email_mask": email_mask,
        "phone_mask": phone_mask,
    }
