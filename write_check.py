python_code = """from app.models import User, UserAPI, UserBot
from app.database import SessionLocal
db = SessionLocal()
for u in db.query(User).all():
    bots = db.query(UserBot).filter(UserBot.user_id == u.id).all()
    apis = db.query(UserAPI).filter(UserAPI.user_id == u.id).all()
    print(f"User {u.id}: bots={[(b.id, b.symbol, b.trade_mode) for b in bots]} apis={[(a.id, a.exchange, a.status) for a in apis]}")
db.close()
"""
with open("check_users.py", "w") as f:
    f.write(python_code)
print("Written")
