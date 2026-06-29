import json
import time

import requests
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Trade, User

router = APIRouter(prefix="/public", tags=["public"])

MARKET_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
    "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT",
]

_ticker_cache: dict = {"data": None, "ts": 0.0}
_CACHE_TTL = 20


@router.get("/market-ticker")
def market_ticker():
    now = time.time()
    if _ticker_cache["data"] and now - _ticker_cache["ts"] < _CACHE_TTL:
        return _ticker_cache["data"]

    url = "https://api.binance.com/api/v3/ticker/24hr"
    params = {"symbols": json.dumps(MARKET_SYMBOLS)}
    try:
        resp = requests.get(url, params=params, timeout=8)
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        if _ticker_cache["data"]:
            return _ticker_cache["data"]
        return {"items": [], "updated_at": None}

    items = []
    for row in raw:
        sym = row.get("symbol", "")
        if sym not in MARKET_SYMBOLS:
            continue
        try:
            price = float(row["lastPrice"])
            change_pct = float(row["priceChangePercent"])
        except (KeyError, TypeError, ValueError):
            continue
        items.append({
            "symbol": sym,
            "base": sym.replace("USDT", ""),
            "price": price,
            "change_pct": round(change_pct, 2),
        })

    order = {s: i for i, s in enumerate(MARKET_SYMBOLS)}
    items.sort(key=lambda x: order.get(x["symbol"], 99))

    payload = {"items": items, "updated_at": int(now)}
    _ticker_cache["data"] = payload
    _ticker_cache["ts"] = now
    return payload


@router.get("/stats")
def platform_stats(db: Session = Depends(get_db)):
    users = db.query(User).count()
    active_api = db.query(User).filter(User.api_status == "active").count()
    total_trades = db.query(Trade).count()
    volume = db.query(func.coalesce(func.sum(Trade.quantity * Trade.entry_price), 0)).scalar() or 0

    closed = db.query(Trade).filter(Trade.status != "open").all()
    wins = sum(1 for t in closed if (t.realized_pnl or 0) > 0)
    win_rate = round(wins / len(closed) * 100, 1) if closed else 0.0

    return {
        "users": max(users, 1),
        "active_api_users": active_api,
        "total_trades": total_trades,
        "trading_volume_usd": round(float(volume), 0),
        "uptime_pct": 99.99,
        "orders_executed": total_trades,
        "win_rate": win_rate,
    }
