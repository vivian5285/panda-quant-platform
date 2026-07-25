#!/usr/bin/env python3
"""Sequential ~20U defense-parallel smoke (rate-limit safe).

For each leg (ETH LONG, ETH SHORT, XAU LONG, XAU SHORT):
  1) webhook OPEN
  2) poll until position + book shows hard STOP + radar STOP + ≥1 TP LIMIT
     (does NOT wait tens of seconds then close without checking defenses)
  3) CLOSE_QUICK_EXIT + mop
  4) cool sleep before next leg (avoid -1003)

Run ON VPS:
  docker compose exec -T -e PYTHONPATH=/app -w /app backend \\
    python /home/panda/panda-quant-platform/backend/data/_vps_defense_parallel_smoke.py

Env:
  WEBHOOK_SECRET, E2E_FORCE_NOTIONAL_USD=20 (set before recreate), SMOKE_COOL_SEC=90
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

SECRET = os.environ.get("WEBHOOK_SECRET", "")
WH = os.environ.get("WEBHOOK_URL", "http://127.0.0.1:6010/webhook")
COOL = float(os.environ.get("SMOKE_COOL_SEC", "95") or 95)
USER_ID = int(os.environ.get("SMOKE_USER_ID", "6") or 6)
ROOT = Path("/home/panda/panda-quant-platform")
OUT = Path(f"/tmp/defense_parallel_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json")


def post(payload: dict) -> str:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(WH, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode()


def public_price(sym: str) -> float:
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}"
    with urllib.request.urlopen(url, timeout=8) as r:
        return float(json.loads(r.read().decode())["price"])


def docker_py(code: str) -> str:
    import subprocess

    p = subprocess.run(
        [
            "docker", "compose", "exec", "-T",
            "-e", "PYTHONPATH=/app", "-w", "/app",
            "backend", "python", "-",
        ],
        input=code,
        text=True,
        cwd=str(ROOT),
        capture_output=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        raise RuntimeError(out)
    return (p.stdout or "").strip()


SNAPSHOT_PY = r'''
import json
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
uid = int(%(uid)d)
sym = "%(sym)s"
db = SessionLocal()
u = db.query(User).filter(User.id == uid).first()
c = BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=uid)
pos = c.get_position(sym) or {}
amt = float(pos.get("positionAmt") or pos.get("size") or 0)
orders = []
try:
    orders = c.get_open_orders(sym) or []
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e), "qty": amt}))
    raise SystemExit(0)
stops = lims = 0
kinds = []
for o in orders:
    t = str(o.get("type") or o.get("orderType") or o.get("origType") or "").upper()
    if "STOP" in t:
        stops += 1
        kinds.append("STOP")
    elif "LIMIT" in t:
        lims += 1
        kinds.append("LIMIT")
    else:
        kinds.append(t or "?")
print(json.dumps({
    "ok": True,
    "qty": abs(amt),
    "side": "LONG" if amt > 0 else ("SHORT" if amt < 0 else ""),
    "n_orders": len(orders),
    "n_stop": stops,
    "n_limit": lims,
    "kinds": kinds[:12],
}))
'''


def snap(sym: str) -> dict:
    raw = docker_py(SNAPSHOT_PY % {"uid": USER_ID, "sym": sym})
    line = [x for x in raw.splitlines() if x.strip().startswith("{")][-1]
    return json.loads(line)


def wait_defenses(sym: str, side: str, timeout: float = 45.0) -> dict:
    """Poll until pos + ≥2 STOP (hard+radar) + ≥1 LIMIT, or timeout."""
    t0 = time.time()
    last = {}
    while time.time() - t0 < timeout:
        last = snap(sym)
        if not last.get("ok"):
            time.sleep(2)
            continue
        qty = float(last.get("qty") or 0)
        n_stop = int(last.get("n_stop") or 0)
        n_lim = int(last.get("n_limit") or 0)
        got_side = str(last.get("side") or "")
        if qty > 0 and got_side == side and n_stop >= 2 and n_lim >= 1:
            last["defense_ok"] = True
            last["elapsed_sec"] = round(time.time() - t0, 2)
            return last
        # Soft pass: small notional may fold TPs → still require dual STOP
        if qty > 0 and got_side == side and n_stop >= 2 and n_lim == 0:
            last["defense_ok"] = False
            last["note"] = "dual_stop_ok_but_no_tp_yet"
            last["elapsed_sec"] = round(time.time() - t0, 2)
        time.sleep(2)
    last["defense_ok"] = bool(
        float(last.get("qty") or 0) > 0
        and int(last.get("n_stop") or 0) >= 2
        and int(last.get("n_limit") or 0) >= 1
    )
    last["elapsed_sec"] = round(time.time() - t0, 2)
    last["timeout"] = True
    return last


def close_flat(sym: str) -> None:
    px = public_price(sym)
    post({
        "secret": SECRET,
        "symbol": f"{sym}.P",
        "action": "CLOSE_QUICK_EXIT",
        "side": "LONG",
        "price": px,
        "reason": "defense_parallel_smoke",
    })
    for _ in range(20):
        s = snap(sym)
        if float(s.get("qty") or 0) <= 0 and int(s.get("n_orders") or 0) == 0:
            return
        time.sleep(2)


def one_leg(sym: str, action: str) -> dict:
    px = public_price(sym)
    atr = 20.0 if sym.startswith("ETH") else 8.0
    sl = px - atr * 1.2 if action == "LONG" else px + atr * 1.2
    tp1 = px + atr * 1.35 if action == "LONG" else px - atr * 1.35
    tp2 = px + atr * 2.5 if action == "LONG" else px - atr * 2.5
    tp3 = px + atr * 4.0 if action == "LONG" else px - atr * 4.0
    payload = {
        "secret": SECRET,
        "symbol": f"{sym}.P",
        "action": action,
        "price": px,
        "stop_loss": round(sl, 4),
        "tp1": round(tp1, 4),
        "tp2": round(tp2, 4),
        "tp3": round(tp3, 4),
        "atr": atr,
        "regime": 3,
        "bar_index": int(time.time()) % 100000,
        "seq": 1,
    }
    wh = post(payload)
    defn = wait_defenses(sym, action, timeout=50)
    close_flat(sym)
    return {
        "symbol": sym,
        "action": action,
        "webhook": wh[:200],
        "defense": defn,
        "pass": bool(defn.get("defense_ok")),
    }


def main() -> int:
    if not SECRET:
        # try runtime
        try:
            from app.config import get_settings
            global SECRET
            SECRET = str(get_settings().WEBHOOK_SECRET or "")
        except Exception:
            pass
    if not SECRET:
        print("WEBHOOK_SECRET missing")
        return 2

    legs = [
        ("ETHUSDT", "LONG"),
        ("ETHUSDT", "SHORT"),
        ("XAUUSDT", "LONG"),
        ("XAUUSDT", "SHORT"),
    ]
    report = {"cool_sec": COOL, "legs": []}
    # pre-flat both
    for sym in ("ETHUSDT", "XAUUSDT"):
        try:
            close_flat(sym)
        except Exception as e:
            report.setdefault("preflat_err", []).append(f"{sym}:{e}")

    for i, (sym, act) in enumerate(legs):
        print(f"=== LEG {i+1}/4 {sym} {act} ===", flush=True)
        try:
            row = one_leg(sym, act)
        except Exception as e:
            row = {"symbol": sym, "action": act, "pass": False, "error": str(e)}
        report["legs"].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if i < len(legs) - 1:
            print(f"cool {COOL}s …", flush=True)
            time.sleep(COOL)

    report["all_pass"] = all(bool(x.get("pass")) for x in report["legs"])
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("WROTE", OUT)
    print("ALL_PASS", report["all_pass"])
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
