from app.database import SessionLocal
from app.models import User, ApiStatus

db = SessionLocal()
users = db.query(User).filter(User.is_active == True).all()
print(f"Active users: {len(users)}")
for u in users[:10]:
    exchange = getattr(u, "exchange", None)
    api_key_set = bool(u.api_key_enc)
    api_status = u.api_status
    print(f"  User {u.id}: uid={u.uid}, exchange={exchange}, api_status={api_status}, api_key_set={api_key_set}")
db.close()
