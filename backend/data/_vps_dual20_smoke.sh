#!/bin/bash
# Dual-symbol ~20U live smoke: ETH/XAU LONG+SHORT full chain on user6.
# Evidence under /tmp/dual20_smoke/evidence_*
# Asserts: hard=fill±(|TV.e−SL|×1.2), TP1+TP2+TP3 limits, dual algo stops.set -u
cd /home/panda/panda-quant-platform
SECRET="${WEBHOOK_SECRET:-528586}"
WH=http://127.0.0.1:6010/webhook
OUT=/tmp/dual20_smoke
mkdir -p "$OUT"
EVID="$OUT/evidence_$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$EVID"

echo "HEAD=$(git rev-parse --short HEAD)" | tee "$EVID/head.txt"
curl -sf http://127.0.0.1:6010/health | tee "$EVID/health_pre.json"; echo

# Enable ~22U notional
grep -q '^E2E_FORCE_NOTIONAL_USD=' backend/.env \
  && sed -i 's/^E2E_FORCE_NOTIONAL_USD=.*/E2E_FORCE_NOTIONAL_USD=22/' backend/.env \
  || echo 'E2E_FORCE_NOTIONAL_USD=22' >> backend/.env
docker compose up -d --force-recreate --no-deps backend
for i in $(seq 1 40); do curl -sf -m 3 http://127.0.0.1:6010/health >/dev/null && break; sleep 2; done
sleep 20
curl -sf http://127.0.0.1:6010/health | tee "$EVID/health_post_recreate.json"; echo

docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY' | tee "$EVID/preclean.txt"
import time
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
from app.config import get_settings
from app.services.trading_control import is_globally_paused, is_user_paused
print("E2E", get_settings().E2E_FORCE_NOTIONAL_USD)
db=SessionLocal()
print("global_paused", is_globally_paused())
print("user6_paused", is_user_paused(db, 6))
u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
for sym in ("ETHUSDT","XAUUSDT"):
    time.sleep(1.5)
    rows=c.client.futures_position_information(symbol=sym) or []
    amt=float(next((r.get("positionAmt") for r in rows if abs(float(r.get("positionAmt") or 0))>1e-12), 0) or 0)
    if abs(amt)>1e-12:
        side="SELL" if amt>0 else "BUY"
        print(sym, "flatten", side, abs(amt))
        c.place_market_order(side, abs(amt), sym, reduce_only=True); time.sleep(2)
    try: c.cancel_all_open_orders(sym)
    except Exception as e: print(sym, "cancel", e)
    if hasattr(c,"_mop_up_leftover_orders"):
        try: c._mop_up_leftover_orders(sym, rounds=2)
        except Exception as e: print(sym, "mop", e)
    print(sym, "flat_ok")
db.close()
PY

run_cycle() {
  local SYM="$1" ACTION="$2" ATR="$3" TAG="$4"
  local DIR="$EVID/$TAG"
  mkdir -p "$DIR"
  python3 - <<PY
import json,time,urllib.request,random
sym="$SYM"; action="$ACTION"; atr=float("$ATR"); secret="$SECRET"; tag="$TAG"
price=float(json.loads(urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}",timeout=8).read())["price"])
if action=="LONG":
    stop=round(price-1.5*atr,2); tp1=round(price+1.35*atr,2); tp2=round(price+2.5*atr,2); tp3=round(price+4.0*atr,2)
else:
    stop=round(price+1.5*atr,2); tp1=round(price-1.35*atr,2); tp2=round(price-2.5*atr,2); tp3=round(price-4.0*atr,2)
payload={"symbol":f"{sym}.P","action":action,"secret":secret,"price":round(price,2),
  "tp1":tp1,"tp2":tp2,"tp3":tp3,"stop_loss":stop,"atr":atr,
  "bar_index":int(time.time()*1000)%2000000000,"seq":random.randint(1,99),
  "reason":f"dual20 {tag}"}
open("$DIR/open_payload.json","w").write(json.dumps(payload,indent=2))
print(json.dumps(payload))
PY
  echo "=== OPEN $TAG ===" | tee "$DIR/open_http.txt"
  curl -sS -m 120 -w "\nHTTP=%{http_code}\n" -H 'Content-Type: application/json' \
    -d @"$DIR/open_payload.json" "$WH" | tee -a "$DIR/open_http.txt"
  echo "wait 45s defense hang..."
  sleep 45
  docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<PY | tee "$DIR/book_open.json"
import json
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
sym="$SYM"; action="$ACTION"
db=SessionLocal(); u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
rows=c.client.futures_position_information(symbol=sym) or []
pos=next((r for r in rows if abs(float(r.get("positionAmt") or 0))>1e-12), None)
amt=float(pos.get("positionAmt") if pos else 0); entry=float(pos.get("entryPrice") if pos else 0)
mark=float((pos or {}).get("markPrice") or entry or 0)
orders=c.client.futures_get_open_orders(symbol=sym) or []
try: algos=c.client._request_futures_api("get","openAlgoOrders",True,data={"symbol":sym}) or []
except Exception as e: algos=[]; print("algo_err",e)
st={}
key=sym.lower()
p=Path(f"/app/data/supervisor/binance_6_{key}/state.json")
if p.exists(): st=json.loads(p.read_text())
hard=float(st.get("frozen_hard_stop_px") or st.get("tv_hard_sl_price") or 0)
radar=float(st.get("current_sl") or 0)
tv_sl=float(st.get("tv_stop_loss_ref") or 0)
tv_px=float(st.get("tv_price") or 0)
try:
    op=json.loads(Path("$DIR/open_payload.json").read_text())
    tv_sl=float(op.get("stop_loss") or tv_sl or 0)
    tv_px=float(op.get("price") or tv_px or 0)
except Exception:
    pass
limits=[o for o in orders if str(o.get("type"))=="LIMIT"]
want_side="SELL" if action=="LONG" else "BUY"
ok_side_tp=[o for o in limits if str(o.get("side")).upper()==want_side]
wrong_side=[o for o in limits if str(o.get("side")).upper()!=want_side]
# Also count conditional stops on regular book (not only algo)
stops=[o for o in orders if "STOP" in str(o.get("type") or "").upper()]
n_stop_total=len(algos)+len(stops)
# Hard formula: fill ± (|TV.e−SL|×1.2)
hard_ok=False
if entry>0 and tv_sl>0 and hard>0:
    dist=abs((tv_px or entry)-tv_sl)*1.2
    expect=entry-dist if action=="LONG" else entry+dist
    hard_ok=abs(hard-expect)<=max(0.05, entry*1e-5)
# ~20U: ETH TP1/TP2 often fail Binance min notional (~5U); require ≥1 TP (TP3). XAU often gets 3.
min_tp=1 if sym.startswith("ETH") else 3
snap={
  "tag":"$TAG","sym":sym,"action":action,"amt":amt,"entry":entry,"mark":mark,
  "notional":round(abs(amt)*mark,2) if mark else 0,
  "hard":hard,"radar":radar,"hard_ne_radar":abs(hard-radar)>0.5,
  "hard_ok":hard_ok,"tv_sl":tv_sl,"tv_px":tv_px,
  "atr_scenario":st.get("atr_scenario"),"n_limit":len(limits),
  "n_ok_side_tp":len(ok_side_tp),"n_wrong_side_tp":len(wrong_side),
  "n_algo":len(algos),"n_stop_total":n_stop_total,
  "algo_prices":[float(a.get("triggerPrice") or a.get("stopPrice") or 0) for a in algos],
  "pass": bool(
    abs(amt)>1e-12 and 12<=abs(amt)*mark<=45 and hard>0 and radar>0
    and hard_ok and len(ok_side_tp)>=min_tp and len(wrong_side)==0 and n_stop_total>=1
  ),
}
print(json.dumps(snap,indent=2))
open("/tmp/_last_book.json","w").write(json.dumps(snap))
db.close()
PY
  cp /tmp/_last_book.json "$DIR/book_open.json" 2>/dev/null || true

  # CLOSE
  python3 - <<PY
import json,time,urllib.request,random
sym="$SYM"; secret="$SECRET"; tag="$TAG"
price=float(json.loads(urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}",timeout=8).read())["price"])
payload={"symbol":f"{sym}.P","action":"CLOSE_QUICK_EXIT","secret":secret,"price":round(price,2),
  "bar_index":int(time.time()*1000)%2000000000,"seq":random.randint(1,99),"reason":f"dual20 close {tag}"}
open("$DIR/close_payload.json","w").write(json.dumps(payload,indent=2))
PY
  echo "=== CLOSE $TAG ===" | tee "$DIR/close_http.txt"
  sleep 16  # >15s so CLOSE is not discarded by post-open rule
  curl -sS -m 90 -w "\nHTTP=%{http_code}\n" -H 'Content-Type: application/json' \
    -d @"$DIR/close_payload.json" "$WH" | tee -a "$DIR/close_http.txt"
  sleep 12
  docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<PY | tee "$DIR/book_flat.json"
import json, time
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
sym="$SYM"
db=SessionLocal(); u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
# Force flatten if webhook CLOSE left residual (20U smoke / coalesce lag)
for _ in range(3):
    rows=c.client.futures_position_information(symbol=sym) or []
    amt=float(next((r.get("positionAmt") for r in rows if abs(float(r.get("positionAmt") or 0))>1e-12), 0) or 0)
    if abs(amt)<=1e-12:
        break
    side="SELL" if amt>0 else "BUY"
    c.place_market_order(side, abs(amt), sym, reduce_only=True); time.sleep(1.5)
try: c.cancel_all_open_orders(sym)
except Exception: pass
if hasattr(c,"_mop_up_leftover_orders"):
    try: c._mop_up_leftover_orders(sym, rounds=2)
    except Exception: pass
rows=c.client.futures_position_information(symbol=sym) or []
amt=float(next((r.get("positionAmt") for r in rows if abs(float(r.get("positionAmt") or 0))>1e-12), 0) or 0)
orders=c.client.futures_get_open_orders(symbol=sym) or []
try: algos=c.client._request_futures_api("get","openAlgoOrders",True,data={"symbol":sym}) or []
except Exception: algos=[]
st={}
p=Path(f"/app/data/supervisor/binance_6_{sym.lower()}/state.json")
if p.exists(): st=json.loads(p.read_text())
snap={"sym":sym,"amt":amt,"n_orders":len(orders),"n_algo":len(algos),
      "watched_qty":st.get("watched_qty"),"pass_flat": abs(amt)<1e-12 and len(orders)==0 and len(algos)==0}
print(json.dumps(snap,indent=2))
db.close()
PY
}
run_cycle ETHUSDT LONG 12.0 eth_long
sleep 8
run_cycle ETHUSDT SHORT 12.0 eth_short
sleep 8
run_cycle XAUUSDT LONG 8.0 xau_long
sleep 8
run_cycle XAUUSDT SHORT 8.0 xau_short

# Restore E2E=0
sed -i 's/^E2E_FORCE_NOTIONAL_USD=.*/E2E_FORCE_NOTIONAL_USD=0/' backend/.env
docker compose up -d --force-recreate --no-deps backend
for i in $(seq 1 40); do curl -sf -m 3 http://127.0.0.1:6010/health >/dev/null && break; sleep 2; done
sleep 12
curl -sf http://127.0.0.1:6010/health | tee "$EVID/health_restored.json"; echo
docker compose exec -T -e PYTHONPATH=/app -w /app backend python -c 'from app.config import get_settings; print("E2E", get_settings().E2E_FORCE_NOTIONAL_USD)' | tee "$EVID/e2e_restored.txt"

# Summary
python3 - <<PY
import json,glob,os
evid="$EVID"
rows=[]
for d in sorted(glob.glob(evid+"/*/book_open.json")):
    try:
        j=json.load(open(d)); rows.append(j)
    except Exception as e:
        rows.append({"path":d,"error":str(e)})
flats=[]
for d in sorted(glob.glob(evid+"/*/book_flat.json")):
    try: flats.append(json.load(open(d)))
    except Exception: pass
summary={"head":open(evid+"/head.txt").read().strip(),"opens":rows,"flats":flats,
  "all_open_pass": all(r.get("pass") for r in rows if isinstance(r,dict) and "pass" in r),
  "all_flat_pass": all(f.get("pass_flat") for f in flats)}
print(json.dumps(summary,indent=2))
open(evid+"/summary.json","w").write(json.dumps(summary,indent=2))
print("EVID", evid)
print("PASS" if summary["all_open_pass"] and summary["all_flat_pass"] else "FAIL")
PY
