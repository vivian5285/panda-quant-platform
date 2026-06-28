from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.models.platform import UserNotification
from app.api.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(unread_only: bool = False, limit: int = 50, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(UserNotification).filter(UserNotification.user_id == user.id)
    if unread_only:
        q = q.filter(UserNotification.is_read == False)
    rows = q.order_by(UserNotification.created_at.desc()).limit(min(limit, 100)).all()
    return [{
        "id": n.id, "category": n.category, "title": n.title, "message": n.message,
        "is_read": n.is_read, "created_at": n.created_at.isoformat() if n.created_at else None,
    } for n in rows]


@router.get("/unread-count")
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.query(UserNotification).filter(UserNotification.user_id == user.id, UserNotification.is_read == False).count()
    return {"count": count}


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.query(UserNotification).filter(UserNotification.id == notification_id, UserNotification.user_id == user.id).first()
    if n:
        n.is_read = True
        db.commit()
    return {"ok": True}


@router.post("/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(UserNotification).filter(UserNotification.user_id == user.id, UserNotification.is_read == False).update({"is_read": True})
    db.commit()
    return {"ok": True}
