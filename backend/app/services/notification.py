from sqlalchemy.orm import Session
from app.models.platform import UserNotification


def notify_user(db: Session, user_id: int, title: str, message: str, category: str = "system"):
    db.add(UserNotification(user_id=user_id, title=title, message=message, category=category))
    db.commit()


def notify_users(db: Session, user_ids: list[int], title: str, message: str, category: str = "system"):
    for uid in user_ids:
        db.add(UserNotification(user_id=uid, title=title, message=message, category=category))
    db.commit()
