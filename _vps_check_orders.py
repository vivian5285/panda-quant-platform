#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, '/home/panda/panda-quant-platform/backend')

from app.core.exchange_factory import ExchangeFactory
from app.database import SessionLocal
from app.models.user import User

async def check_orders():
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.exchange == 'binance').filter(User.api_key.isnot(None)).all()
        print(f"=== Found {len(users)} binance users ===")
        for u in users:
            try:
                if u.exchange_api:
                    key = u.exchange_api.decrypt_key()
                    secret = u.exchange_api.decrypt_secret()
                    client = ExchangeFactory.create_client(u.exchange, key, secret)
                    pos = client.get_position()
                    orders = client.get_open_orders()
                    print(f"\nUser {u.id} ({u.username}):")
                    print(f"  Position: {pos}")
                    print(f"  Open orders: {len(orders) if orders else 0}")
                    if orders:
                        for o in orders:
                            print(f"    - {o.get('symbol')} {o.get('side')} {o.get('type')} qty={o.get('origQty')} price={o.get('price')} stopPrice={o.get('stopPrice')}")
            except Exception as e:
                print(f"  Error: {e}")
    finally:
        db.close()

asyncio.run(check_orders())
