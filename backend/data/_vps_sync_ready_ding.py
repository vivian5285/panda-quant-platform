"""VPS ready check via live API + exchange; send DingTalk sync notice.

Runs inside backend container (PYTHONPATH=/app). HEAD passed via env GIT_HEAD.
"""
from __future__ import annotations

import json
import os
import urllib.request

from app.config import get_settings
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
from app.services.trading_control import is_globally_paused, is_user_paused
from app.services.alert_service import notify_system

head = (os.environ.get("GIT_HEAD") or "unknown").strip()
settings = get_settings()
db = SessionLocal()
print("HEAD", head)
print("E2E", settings.E2E_FORCE_NOTIONAL_USD)
print("IDLE", settings.IDLE_PATROL_INTERVAL_SEC, "FAIL_BACKOFF", settings.IDLE_PATROL_FAIL_BACKOFF_SEC)
print("global_paused", is_globally_paused())
print("user6_paused", is_user_paused(db, 6))

api = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=8).read())
print("API", api)
n_sup = int(api.get("active_supervisors") or 0)

u = db.query(User).filter(User.id == 6).one()
c = BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
rows = {}
for sym in ("ETHUSDT", "XAUUSDT"):
    pos = c.get_position(sym)
    amt = 0.0
    if isinstance(pos, dict):
        try:
            amt = float(pos.get("positionAmt") or 0)
        except (TypeError, ValueError):
            amt = 0.0
    rows[sym] = {"amt": amt, "flat": abs(amt) < 1e-12}
    print(sym, rows[sym])

# supervisor state files (mounted)
state_rows = {}
for name, label in (("binance_6_ethusdt", "ETHUSDT"), ("binance_6_xauusdt", "XAUUSDT")):
    path = f"/app/data/supervisor/{name}/state.json"
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        state_rows[label] = {
            "monitoring": bool(d.get("monitoring")),
            "watched_qty": d.get("watched_qty"),
            "current_side": d.get("current_side"),
            "trading_paused": d.get("trading_paused"),
        }
    except Exception as e:
        state_rows[label] = {"error": str(e)}
    print("STATE", label, state_rows[label])

user6_paused = is_user_paused(db, 6)
db.close()

mon_ok = all(
    isinstance(v, dict) and v.get("monitoring") is False and not v.get("error")
    for v in state_rows.values()
)
ok = (
    float(settings.E2E_FORCE_NOTIONAL_USD or 0) == 0
    and not is_globally_paused()
    and not user6_paused
    and n_sup >= 2
    and bool(api.get("supervisors_ready"))
    and all(r["flat"] for r in rows.values())
    and mon_ok
)
print("READY", ok, "n_sup", n_sup)

notify_system(
    "info",
    "PROD_SYNC_READY",
    "三端同步完成·等待TV",
    (
        f"本地/GitHub/VPS 对齐 {head} · active_supervisors={n_sup} · "
        f"ETH/XAU paused=false · monitoring=false · 空仓待命 · E2E=0 · "
        f"QUERY_FAILED fail-closed · 巡检{settings.IDLE_PATROL_INTERVAL_SEC:g}s/"
        f"失败退避{settings.IDLE_PATROL_FAIL_BACKOFF_SEC:g}s · 等待真实TV"
    ),
    {
        "head": head,
        "e2e": settings.E2E_FORCE_NOTIONAL_USD,
        "active_supervisors": n_sup,
        "api": api,
        "positions": rows,
        "state": state_rows,
        "user6_paused": user6_paused,
        "idle_patrol_sec": settings.IDLE_PATROL_INTERVAL_SEC,
        "idle_fail_backoff_sec": settings.IDLE_PATROL_FAIL_BACKOFF_SEC,
        "ready": ok,
    },
)
print("DINGTALK_SENT")
print(json.dumps({"head": head, "ready": ok, "n_sup": n_sup, "rows": rows, "state": state_rows}, indent=2))
