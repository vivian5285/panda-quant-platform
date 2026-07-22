#!/bin/bash
# Dual ETH+XAU E2E v2 — sequential opens, correct XAU step, no absurd TV qty slices.
set -eu
cd /home/panda/panda-quant-platform
WH_URL="${WEBHOOK_URL:-https://twinstar.pro/gemini/webhook}"
SECRET=528586

echo "===UTC $(date -u +%Y-%m-%dT%H:%M:%SZ) HEAD=$(git log -1 --oneline)==="
curl -sf -m 5 http://127.0.0.1:6010/health; echo

echo "===PREFLIGHT flat + cool-down 70s for Binance IP weight==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
import json, time
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
from app.core.symbol_registry import symbol_meta

db = SessionLocal()
u = db.query(User).filter(User.id == 6).one()
c = BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
meta = symbol_meta("XAUUSDT")
print("XAU_meta", {k: str(meta.get(k)) for k in ("qty_step","min_qty","qty_decimals")})
for sym in ("ETHUSDT", "XAUUSDT"):
    try:
        c.cancel_all_open_orders(sym)
    except Exception as e:
        print(sym, "cancel", e)
    pos = c.get_position(sym) or {}
    amt = float(pos.get("positionAmt") or 0)
    if abs(amt) > 1e-12:
        side = "SELL" if amt > 0 else "BUY"
        print(sym, "flatten", c.place_market_order(side, abs(amt), sym, reduce_only=True))
        time.sleep(1)
    else:
        print(sym, "flat")
for name in ("binance_6_ethusdt", "binance_6_xauusdt"):
    p = Path(f"/app/data/supervisor/{name}/state.json")
    if p.exists():
        s = json.loads(p.read_text())
        s.update({"monitoring": False, "watched_qty": 0.0, "current_side": None,
                  "trading_paused": False, "adverse_sl_armed": False})
        p.write_text(json.dumps(s, ensure_ascii=False))
db.close()
print("sleep 70 for rate-limit cool-down")
time.sleep(70)
print("PREFLIGHT_OK")
PY

post_open() {
  local SYM="$1" ATR="$2" REGIME="$3"
  python3 - <<PY
import json, time, urllib.request
sym="$SYM"; atr=float("$ATR"); secret="$SECRET"; regime=int("$REGIME")
price=float(json.loads(urllib.request.urlopen(
  f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}", timeout=10).read())["price"])
# omit qty1/qty2 so engine uses 30/30 of live qty
payload={
  "symbol": f"{sym}.P", "action": "LONG", "secret": secret,
  "price": round(price, 2), "qty": 0.02,
  "tp1": round(price + 1.35*atr, 2),
  "tp2": round(price + 2.5*atr, 2),
  "tp3": round(price + 4.0*atr, 2),
  "stop_loss": round(price - 1.5*atr, 2),
  "atr": atr, "regime": regime,
  "bar_index": int(time.time()), "seq": 1,
  "reason": "E2E dual v2",
}
path=f"/tmp/e2e_v2_{sym.lower()}_open.json"
open(path,"w").write(json.dumps(payload))
print("PAYLOAD", json.dumps(payload))
PY
  curl -sS -m 60 -w "\nHTTP=%{http_code}\n" -H 'Content-Type: application/json' \
    -d @"/tmp/e2e_v2_${SYM,,}_open.json" "$WH_URL"
  echo
}

echo "===OPEN ETH then wait 25s==="
post_open ETHUSDT 14.5 3
sleep 25

echo "===OPEN XAU then wait 25s==="
post_open XAUUSDT 8.0 1
sleep 25

echo "===VERIFY==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
import json
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
from app.core.breathing_profile import profile_for_symbol

db = SessionLocal()
u = db.query(User).filter(User.id == 6).one()
c = BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
report = {"ok": True, "symbols": {}}

def list_algos(sym):
    try:
        return c.get_open_algo_orders(sym) or []
    except Exception as e:
        return [{"_err": str(e)}]

for sym, sk in (("ETHUSDT", "binance_6_ethusdt"), ("XAUUSDT", "binance_6_xauusdt")):
    rec = {}
    rows = c.client.futures_position_information(symbol=sym)
    pos = next((r for r in rows if abs(float(r.get("positionAmt") or 0)) > 1e-12), None)
    if not pos:
        rec["pos"] = "FLAT"; rec["ok"] = False; report["ok"] = False
    else:
        amt = float(pos["positionAmt"]); entry = float(pos["entryPrice"]); mark = float(pos.get("markPrice") or entry)
        rec["pos"] = {"amt": amt, "entry": entry, "notional": round(abs(amt)*mark, 2)}
        rec["ok"] = True
    orders = c.client.futures_get_open_orders(symbol=sym)
    tps = [o for o in orders if str(o.get("type")).upper() == "LIMIT" and o.get("reduceOnly")]
    rec["tp_orders"] = [
        {"qty": o.get("origQty"), "price": o.get("price")} for o in tps
    ]
    rec["tp_count"] = len(tps)
    algos = list_algos(sym)
    rec["algo"] = [
        {"type": a.get("orderType") or a.get("type"), "trigger": a.get("triggerPrice") or a.get("stopPrice"),
         "qty": a.get("quantity")}
        for a in algos if "_err" not in a
    ]
    if algos and "_err" in (algos[0] or {}):
        rec["algo_err"] = algos[0]["_err"]
    rec["sl_count"] = len(rec["algo"])
    st = json.loads(Path(f"/app/data/supervisor/{sk}/state.json").read_text())
    rec["state"] = {k: st.get(k) for k in (
        "monitoring","current_side","watched_qty","initial_atr","current_sl",
        "breathing_coefficient","breakeven_phase","tv_tps")}
    p = profile_for_symbol(sym)
    rec["profile"] = {"early_be": p.early_breakeven_atr, "step": p.step_trigger_atr,
                      "advance": p.step_advance_atr, "buffer": p.stop_order_buffer}
    # require: pos + >=2 TP + >=1 SL + monitoring
    if rec.get("pos") == "FLAT" or rec["tp_count"] < 2 or rec["sl_count"] < 1 or not st.get("monitoring"):
        rec["ok"] = False
        report["ok"] = False
    report["symbols"][sym] = rec
    print(sym, json.dumps(rec, ensure_ascii=False))

eth = report["symbols"]["ETHUSDT"]
xau = report["symbols"]["XAUUSDT"]
report["isolation"] = {
    "sl_gap": abs(float(eth["state"].get("current_sl") or 0) - float(xau["state"].get("current_sl") or 0)),
    "atr_gap": abs(float(eth["state"].get("initial_atr") or 0) - float(xau["state"].get("initial_atr") or 0)),
    "xau_tighter_be": xau["profile"]["early_be"] < eth["profile"]["early_be"],
}
if report["isolation"]["sl_gap"] < 10 or not report["isolation"]["xau_tighter_be"]:
    report["ok"] = False
print("REPORT", json.dumps({"ok": report["ok"], "isolation": report["isolation"]}, ensure_ascii=False))
Path("/home/panda/panda-quant-platform/backend/data/_e2e_dual_v2_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2)
)
db.close()
raise SystemExit(0 if report["ok"] else 2)
PY

echo "===CLOSE BOTH via webhook==="
for SYM in ETHUSDT XAUUSDT; do
python3 - <<PY
import json,time,urllib.request
sym="$SYM"
price=float(json.loads(urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}", timeout=10).read())["price"])
payload={"symbol":f"{sym}.P","action":"CLOSE_QUICK_EXIT","secret":"$SECRET","side":"LONG",
 "price":round(price,2),"reason":"E2E dual v2 flatten","pnl_pct":-0.1,
 "bar_index":int(time.time()),"seq":9}
open(f"/tmp/e2e_v2_{sym.lower()}_close.json","w").write(json.dumps(payload))
print(payload)
PY
curl -sS -m 45 -w "\nHTTP=%{http_code}\n" -H 'Content-Type: application/json' \
  -d @"/tmp/e2e_v2_${SYM,,}_close.json" "$WH_URL"
echo
sleep 12
done

echo "===SAFETY FLATTEN==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
import json, time
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
db=SessionLocal(); u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
ok=True
for sym in ("ETHUSDT","XAUUSDT"):
    try: c.cancel_all_open_orders(sym)
    except Exception as e: print(sym,"cancel",e)
    pos=c.get_position(sym) or {}
    amt=float(pos.get("positionAmt") or 0)
    if abs(amt)>1e-12:
        side="SELL" if amt>0 else "BUY"
        print(sym,"FORCE",c.place_market_order(side,abs(amt),sym,reduce_only=True)); time.sleep(1); ok=False
    rows=c.client.futures_position_information(symbol=sym)
    live=[r for r in rows if abs(float(r.get("positionAmt") or 0))>1e-12]
    orders=c.client.futures_get_open_orders(symbol=sym)
    print(sym, "flat" if not live else live[0].get("positionAmt"), "orders", len(orders))
    if live or orders: ok=False
for name in ("binance_6_ethusdt","binance_6_xauusdt"):
    p=Path(f"/app/data/supervisor/{name}/state.json")
    if p.exists():
        s=json.loads(p.read_text())
        print(name,{k:s.get(k) for k in ("monitoring","watched_qty","current_side")})
print("FINAL_OK" if ok else "FINAL_NEED_CHECK")
db.close()
PY
echo "===E2E DUAL V2 DONE==="
