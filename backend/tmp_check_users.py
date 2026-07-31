#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.models import User

db = SessionLocal()
users = db.query(User).filter(User.is_active == True, User.api_key_enc.isnot(None)).all()
print(f'Active users with API: {len(users)}')
for u in users:
    print(f'  user_id={u.id} uid={u.uid} exchange={getattr(u, "exchange", None)} api_status={u.api_status}')
db.close()
