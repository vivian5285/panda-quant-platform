#!/bin/bash
# Min-notional (~22 USD) live TV simulation: ETH/XAU × LONG/SHORT
set -u
cd /home/panda/panda-quant-platform
SECRET="${WEBHOOK_SECRET:-528586}"
WH="${WEBHOOK_URL:-http://127.0.0.1:6010/webhook}"
export E2E_FORCE_NOTIONAL_USD=22

echo "===UTC $(date -u +%Y-%m-%dT%H:%M:%SZ)==="
echo "===HEAD $(git rev-parse --short HEAD)==="
# Enable e2e notional in .env and recreate backend so settings reload
if [ -f backend/.env ]; then
  grep -q '^E2E_FORCE_NOTIONAL_USD=' backend/.env \
    && sed -i 's/^E2E_FORCE_NOTIONAL_USD=.*/E2E_FORCE_NOTIONAL_USD=22/' backend/.env \
    || echo 'E2E_FORCE_NOTIONAL_USD=22' >> backend/.env
fi
docker compose up -d backend
for i in $(seq 1 24); do
  curl -sf -m 3 http://127.0.0.1:6010/health >/dev/null && break
  sleep 3
done
curl -sf http://127.0.0.1:6010/health; echo

docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
from app.config import get_settings
from app.core.breathing_profile import ETH_PROFILE, XAU_PROFILE, cold_start_multiplier, RATIO_FLOOR, RATIO_CEILING
s=get_settings()
print("E2E_FORCE", s.E2E_FORCE_NOTIONAL_USD)
print("COALESCE", s.WEBHOOK_COALESCE_SEC)
assert float(s.E2E_FORCE_NOTIONAL_USD) == 22.0
assert ETH_PROFILE.coef_min==1.2 and ETH_PROFILE.coef_max==2.5
assert XAU_PROFILE.coef_min==0.5 and XAU_PROFILE.coef_max==1.2
assert ETH_PROFILE.step_advance_atr==0.4 and XAU_PROFILE.step_advance_atr==0.35
assert ETH_PROFILE.chart_tf_min==90.0 and XAU_PROFILE.chart_tf_min==45.0
assert ETH_PROFILE.stagnant_window_min==90.0 and XAU_PROFILE.stagnant_window_min==60.0
assert ETH_PROFILE.early_breakeven_atr==0.5 and XAU_PROFILE.early_breakeven_atr==0.3
assert ETH_PROFILE.phase2_trigger_atr==3.0 and XAU_PROFILE.phase2_trigger_atr==3.0
assert RATIO_FLOOR==0.6 and RATIO_CEILING==2.2
assert abs(cold_start_multiplier(ETH_PROFILE)-1.525)<1e-9
assert abs(cold_start_multiplier(XAU_PROFILE)-0.675)<1e-9
print("PROFILE_LOCK_TABLE_OK")
PY

# flat clean
bash /tmp/_vps_flat_clean.sh 2>/dev/null || true
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
import json, time
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
from app.services.trading_control import is_globally_paused, is_user_paused, set_user_control
db=SessionLocal()
assert not is_globally_paused()
if is_user_paused(db,6):
    set_user_control(db,6,trading_paused=False)
u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
for sym in ("ETHUSDT","XAUUSDT"):
    try: c.cancel_all_open_orders(sym)
    except Exception: pass
    for meth in ("cancel_all_algo_orders","cancel_all_close_stops"):
        fn=getattr(c,meth,None)
        if callable(fn):
            try: fn(sym)
            except Exception: pass
    try:
        for o in (c.client._request_futures_api("get","openAlgoOrders",True,{"symbol":sym}) or []):
            try: c.client._request_futures_api("delete","algoOrder",True,{"symbol":sym,"algoId":o.get("algoId") or o.get("clientAlgoId")})
            except Exception: pass
    except Exception: pass
    amt=float((c.get_position(sym) or {}).get("positionAmt") or 0)
    if abs(amt)>1e-12:
        side="SELL" if amt>0 else "BUY"
        c.place_market_order(side, abs(amt), sym, reduce_only=True); time.sleep(1)
    for name in (f"binance_6_{sym.lower()}",):
        for base in (Path("/app/data/supervisor"), Path("/home/panda/panda-quant-platform/backend/data/supervisor")):
            p=base/name/"state.json"
            if p.exists():
                s=json.loads(p.read_text())
                for k,v in {"monitoring":False,"watched_qty":0.0,"current_side":None,"trading_paused":False,"current_sl":0.0,"initial_atr":0.0,"_frozen_hard_stop_px":0.0,"_tv_hard_sl_price":0.0,"tp3_limit_active":False,"atr_scenario":""}.items():
                    s[k]=v
                p.write_text(json.dumps(s,ensure_ascii=False))
print("PRE_FLAT_OK")
db.close()
PY

post() { curl -sS -m 90 -w "\nHTTP=%{http_code}\n" -H 'Content-Type: application/json' -d @"$1" "$WH"; }

build_open() {
  local SYM="$1" ACTION="$2" ATR="$3" OUT="$4"
  docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<PY
import json, time, urllib.request
sym, action, atr = "$SYM", "$ACTION", float("$ATR")
secret="$SECRET"
price=float(json.loads(urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}", timeout=8).read())["price"])
dp = 2 if sym.startswith("ETH") else 3
if action=="LONG":
    stop=round(price-1.5*atr, dp); tp1=round(price+1.35*atr, dp); tp2=round(price+2.5*atr, dp); tp3=round(price+4.0*atr, dp)
else:
    stop=round(price+1.5*atr, dp); tp1=round(price-1.35*atr, dp); tp2=round(price-2.5*atr, dp); tp3=round(price-4.0*atr, dp)
payload={"symbol":sym+".P","action":action,"secret":secret,"price":round(price,dp),
 "tp1":tp1,"tp2":tp2,"tp3":tp3,"stop_loss":stop,"atr":atr,
 "regime": 3 if sym.startswith("ETH") else 1,
 "bar_index":int(time.time()),"seq":1,"reason":f"min20u {action} {sym}"}
open("$OUT","w").write(json.dumps(payload)); print(json.dumps(payload))
PY
}

verify_open() {
  local SYM="$1" SIDE="$2" TAG="$3"
  docker compose exec -T -e PYTHONPATH=/app -w /app -e SYM="$SYM" -e SIDE="$SIDE" -e TAG="$TAG" backend python - <<'PY'
import json, os
from collections import Counter
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
from app.core.breathing_profile import profile_for_symbol, cold_start_multiplier

sym, side, tag = os.environ["SYM"], os.environ["SIDE"].upper(), os.environ["TAG"]
db=SessionLocal(); u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
pos=c.get_position(sym) or {}
amt=float(pos.get("positionAmt") or 0)
entry=float(pos.get("entryPrice") or 0)
mark=float(pos.get("markPrice") or entry or 0)
notional=abs(amt)*mark
orders=c.client.futures_get_open_orders(symbol=sym) or []
try: algos=c.client._request_futures_api("get","openAlgoOrders",True,{"symbol":sym}) or []
except Exception as e: algos=[]; print("algo_err",e)
print("ORDERS:")
for o in orders:
    print(" ", o.get("type"), o.get("side"), o.get("origQty"), "@", o.get("stopPrice") or o.get("price"))
print("ALGOS:")
for a in algos:
    print(" ", a.get("orderType") or a.get("type"), a.get("quantity"), "@", a.get("triggerPrice") or a.get("stopPrice"))
st={}
for base in (Path("/app/data/supervisor"), Path("/home/panda/panda-quant-platform/backend/data/supervisor")):
    p=base/f"binance_6_{sym.lower()}"/"state.json"
    if p.exists(): st=json.loads(p.read_text()); break
hard=float(st.get("_frozen_hard_stop_px") or st.get("_tv_hard_sl_price") or 0)
radar=float(st.get("current_sl") or 0)
prof=profile_for_symbol(sym)
tp=[o for o in orders if str(o.get("type")) in ("LIMIT","TAKE_PROFIT","TAKE_PROFIT_MARKET") and str(o.get("reduceOnly")).lower() in ("true","1")]
pxc=Counter(float(o.get("price") or 0) for o in tp)
stops=len(algos)+sum(1 for o in orders if "STOP" in str(o.get("type") or ""))
side_ok=(amt>0 and side=="LONG") or (amt<0 and side=="SHORT")
# hard vs radar distinct; notional near 20
ok = (
  side_ok and 15 <= notional <= 35 and hard>0 and radar>0 and abs(hard-radar)>1e-6
  and len(tp)>=2 and (max(pxc.values()) if pxc else 0)<=1 and stops>=2
  and bool(st.get("monitoring")) and float(st.get("initial_atr") or 0)>0
  and float(st.get("breathing_coefficient") or 0)>0
)
# hard direction check
if side=="LONG" and hard>0 and entry>0:
    ok = ok and hard < entry
if side=="SHORT" and hard>0 and entry>0:
    ok = ok and hard > entry
report={
 "tag":tag,"symbol":sym,"side":side,"amt":amt,"entry":entry,"notional":round(notional,2),
 "hard":hard,"radar":radar,"atr_scenario":st.get("atr_scenario"),
 "initial_atr":st.get("initial_atr"),"coef":st.get("breathing_coefficient"),
 "cold_expect":cold_start_multiplier(prof),"profile":{"min":prof.coef_min,"max":prof.coef_max,"step_advance":prof.step_advance_atr,"chart_tf":prof.chart_tf_min},
 "tp":len(tp),"stops":stops,"max_same_tp": (max(pxc.values()) if pxc else 0),
 "ok":ok
}
print(json.dumps(report,ensure_ascii=False,indent=2))
open(f"/tmp/min20_{tag}.json","w").write(json.dumps(report,ensure_ascii=False,indent=2))
db.close()
raise SystemExit(0 if ok else 2)
PY
}

run_one() {
  local SYM="$1" ACTION="$2" ATR="$3" TAG="$4"
  echo "======== $TAG $SYM $ACTION ========"
  build_open "$SYM" "$ACTION" "$ATR" "/tmp/${TAG}_open.json"
  docker compose exec -T backend cat "/tmp/${TAG}_open.json" > "/tmp/${TAG}_open.json"
  post "/tmp/${TAG}_open.json"
  # wait past 15s coalesce window for open to flush + execute
  sleep 18
  verify_open "$SYM" "$ACTION" "$TAG" || return 1
  echo "=== hold observe 12s ==="
  sleep 12
  docker compose logs --since 3m backend 2>/dev/null | grep -E "User 6|${SYM:0:3}|ATR_SCENARIO|硬止损|雷达|TP1|TP2|WebhookCoalesce|E2E|算仓|notional|duplicate|Traceback|ERROR" | tail -40 || true
  docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<PY
import json,time,urllib.request
sym="$SYM"; secret="$SECRET"; side="$ACTION"
price=float(json.loads(urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}", timeout=8).read())["price"])
dp=2 if sym.startswith("ETH") else 3
payload={"symbol":sym+".P","action":"CLOSE_QUICK_EXIT","secret":secret,"side":side,"price":round(price,dp),"reason":"min20u close $TAG","pnl_pct":-0.1,"bar_index":int(time.time()),"seq":9}
open("/tmp/${TAG}_close.json","w").write(json.dumps(payload)); print(payload)
PY
  docker compose exec -T backend cat "/tmp/${TAG}_close.json" > "/tmp/${TAG}_close.json"
  # ensure >15s after open already; post close
  post "/tmp/${TAG}_close.json"
  sleep 14
  docker compose exec -T -e PYTHONPATH=/app -w /app -e SYM="$SYM" backend python - <<'PY'
import os
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
sym=os.environ["SYM"]
db=SessionLocal(); u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
amt=float((c.get_position(sym) or {}).get("positionAmt") or 0)
orders=c.client.futures_get_open_orders(symbol=sym) or []
try: algos=c.client._request_futures_api("get","openAlgoOrders",True,{"symbol":sym}) or []
except Exception: algos=[]
print({"symbol":sym,"flat":abs(amt)<1e-12,"orders":len(orders),"algos":len(algos)})
assert abs(amt)<1e-12 and len(orders)==0 and len(algos)==0
print("POST_CLOSE_CLEAN")
db.close()
PY
}

FAIL=0
run_one ETHUSDT LONG 25 eth_long || FAIL=1
run_one ETHUSDT SHORT 25 eth_short || FAIL=1
run_one XAUUSDT LONG 12 xau_long || FAIL=1
run_one XAUUSDT SHORT 12 xau_short || FAIL=1

echo "===DISABLE E2E FORCE (production)==="
sed -i 's/^E2E_FORCE_NOTIONAL_USD=.*/E2E_FORCE_NOTIONAL_USD=0/' backend/.env
docker compose up -d backend
for i in $(seq 1 24); do curl -sf -m 3 http://127.0.0.1:6010/health >/dev/null && break; sleep 3; done
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
from app.config import get_settings
print("E2E_FORCE_AFTER", get_settings().E2E_FORCE_NOTIONAL_USD)
assert float(get_settings().E2E_FORCE_NOTIONAL_USD)==0.0
print("E2E_OFF_OK")
PY

echo "===FINAL==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
db=SessionLocal(); u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
ok=True
for sym in ("ETHUSDT","XAUUSDT"):
  amt=float((c.get_position(sym) or {}).get("positionAmt") or 0)
  orders=c.client.futures_get_open_orders(symbol=sym) or []
  try: algos=c.client._request_futures_api("get","openAlgoOrders",True,{"symbol":sym}) or []
  except Exception: algos=[]
  print(sym,"amt",amt,"orders",len(orders),"algos",len(algos))
  if abs(amt)>1e-12 or orders or algos: ok=False
print("FINAL_OK" if ok else "FINAL_DIRTY")
raise SystemExit(0 if ok else 3)
PY
echo "FAIL=$FAIL"
test "$FAIL" = "0" && echo "ALL_CYCLES_OK" || echo "SOME_CYCLES_FAILED"
exit $FAIL
