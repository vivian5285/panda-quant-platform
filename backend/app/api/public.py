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

COINGECKO_IDS = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum",
    "BNBUSDT": "binancecoin",
    "SOLUSDT": "solana",
    "XRPUSDT": "ripple",
    "DOGEUSDT": "dogecoin",
    "ADAUSDT": "cardano",
    "AVAXUSDT": "avalanche-2",
    "LINKUSDT": "chainlink",
    "DOTUSDT": "polkadot",
}

_ticker_cache: dict = {"data": None, "ts": 0.0}
_CACHE_TTL = 15


def _parse_binance(raw: list) -> list[dict]:
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
    return items


def _fetch_coingecko() -> list[dict]:
    ids = ",".join(COINGECKO_IDS.values())
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ids,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    id_to_sym = {v: k for k, v in COINGECKO_IDS.items()}
    items = []
    for cg_id, row in data.items():
        sym = id_to_sym.get(cg_id)
        if not sym:
            continue
        try:
            price = float(row["usd"])
            change_pct = float(row.get("usd_24h_change") or 0)
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
    return items


@router.get("/market-ticker")
def market_ticker():
    now = time.time()
    if _ticker_cache["data"] and now - _ticker_cache["ts"] < _CACHE_TTL:
        return _ticker_cache["data"]

    items: list[dict] = []
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        params = {"symbols": json.dumps(MARKET_SYMBOLS)}
        resp = requests.get(url, params=params, timeout=8)
        resp.raise_for_status()
        items = _parse_binance(resp.json())
    except Exception:
        items = []

    if not items:
        try:
            items = _fetch_coingecko()
        except Exception:
            items = []

    if not items and _ticker_cache["data"]:
        return _ticker_cache["data"]

    payload = {"items": items, "updated_at": int(now) if items else None}
    if items:
        _ticker_cache["data"] = payload
        _ticker_cache["ts"] = now
    return payload


@router.get("/platform-config")
def platform_config():
    from app.services.platform_public_settings import get_platform_public_settings

    return get_platform_public_settings()


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
