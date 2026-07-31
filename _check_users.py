import sys
import json
sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.models import User, ApiStatus

db = SessionLocal()
try:
    users = db.query(User).filter(
        User.is_active == True,
        User.api_status == ApiStatus.ACTIVE.value,
        User.api_key_enc.isnot(None),
    ).all()

    print(f"Found {len(users)} active users with API credentials:")

    for u in users:
        print(f"  User ID={u.id}, uid={u.uid}, exchange={u.exchange}, api_status={u.api_status}, is_active={u.is_active}")

    if not users:
        all_users = db.query(User).all()
        print(f"Total users in DB: {len(all_users)}")
        for u in all_users[:10]:
            print(f"  User ID={u.id}, uid={u.uid}, api_status={u.api_status}, is_active={u.is_active}, has_key={bool(u.api_key_enc)}")

finally:
    db.close()
