#!/bin/bash
# Whitepaper §十四 终极内测：ETH+XAU 最小名义≈20U · 场景一 · 15s铁律 · 洁净收尾
# 在 VPS: bash backend/data/_whitepaper_final_live_test.sh
set -eu
cd /home/panda/panda-quant-platform
SECRET="${WEBHOOK_SECRET:-528586}"
WH_URL="${WEBHOOK_URL:-http://127.0.0.1:6010/webhook}"
# 临时把算仓压到约 min notional（仅本脚本进程内生效，需代码支持 E2E_FORCE_NOTIONAL_USD）
export E2E_FORCE_NOTIONAL_USD="${E2E_FORCE_NOTIONAL_USD:-22}"

echo "===UTC $(date -u +%Y-%m-%dT%H:%M:%SZ)==="
echo "===HEAD $(git rev-parse --short HEAD) $(git log -1 --oneline)==="
curl -sf -m 5 http://127.0.0.1:6010/health; echo
curl -sf -m 5 http://127.0.0.1:8000/health; echo

echo "===PREFLIGHT flat+clean user6==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
import json, time
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
from app.services.trading_control import is_globally_paused, is_user_paused, set_user_paused

db = SessionLocal()
assert not is_globally_paused(), "global paused"
if is_user_paused(db, 6):
    set_user_paused(db, 6, False, reason="whitepaper_preflight")
    print("user6 unpaused")
u = db.query(User).filter(User.id == 6).one()
c = BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
summary = c.get_futures_account_summary() or {}
equity = float(summary.get("total_margin_balance") or summary.get("totalWalletBalance") or 0)
print("equity", equity, "avail", summary.get("available_balance"))

for sym in ("ETHUSDT", "XAUUSDT"):
    try:
        c.cancel_all_open_orders(sym)
    except Exception as e:
        print(sym, "cancel_orders", e)
    for meth in ("cancel_all_algo_orders", "cancel_all_close_stops"):
        fn = getattr(c, meth, None)
        if callable(fn):
            try:
                print(sym, meth, fn(sym))
            except Exception as e:
                print(sym, meth, type(e).__name__, e)
    try:
        r = c.client._request_futures_api("get", "openAlgoOrders", True, {"symbol": sym}) or []
        for o in r:
            try:
                c.client._request_futures_api("delete", "algoOrder", True, {
                    "symbol": sym, "algoId": o.get("algoId") or o.get("clientAlgoId"),
                })
            except Exception:
                pass
    except Exception as e:
        print(sym, "algo", type(e).__name__)
    pos = c.get_position(sym) or {}
    amt = float(pos.get("positionAmt") or 0)
    if abs(amt) > 1e-12:
        side = "SELL" if amt > 0 else "BUY"
        print(sym, "FORCE_FLAT", side, abs(amt))
        print(c.place_market_order(side, abs(amt), sym, reduce_only=True))
        time.sleep(1.2)
    orders = c.client.futures_get_open_orders(symbol=sym) or []
    try:
        algos = c.client._request_futures_api("get", "openAlgoOrders", True, {"symbol": sym}) or []
    except Exception:
        algos = []
    print(sym, "flat_ok", abs(float((c.get_position(sym) or {}).get("positionAmt") or 0)) < 1e-12,
          "orders", len(orders), "algos", len(algos))
    assert abs(float((c.get_position(sym) or {}).get("positionAmt") or 0)) < 1e-12
    assert len(orders) == 0 and len(algos) == 0, f"{sym} leftover orders/algos"

for name in ("binance_6_ethusdt", "binance_6_xauusdt"):
    for base in (Path("/app/data/supervisor"), Path("/home/panda/panda-quant-platform/backend/data/supervisor")):
        p = base / name / "state.json"
        if not p.exists():
            continue
        s = json.loads(p.read_text())
        for k, v in {
            "monitoring": False, "watched_qty": 0.0, "current_side": None,
            "adverse_sl_armed": False, "adverse_sl_prices": [],
            "trading_paused": False, "trading_pause_reason": "",
            "breakeven_phase": False, "current_sl": 0.0, "initial_stop": 0.0,
            "initial_atr": 0.0, "best_price": 0.0, "radar_activated": False,
            "radar_latched": False, "consumed_tp_levels": [],
            "tp3_limit_active": False, "atr_scenario": "",
            "_frozen_hard_stop_px": 0.0, "_tv_hard_sl_price": 0.0,
        }.items():
            s[k] = v
        p.write_text(json.dumps(s, ensure_ascii=False))
        print("state_reset", p)
db.close()
print("PREFLIGHT_OK")
PY

post_json() {
  local file="$1"
  curl -sS -m 90 -w "\nHTTP=%{http_code}\n" -H 'Content-Type: application/json' -d @"$file" "$WH_URL"
}

build_payload() {
  local SYM="$1" ACTION="$2" ATR="$3" SIDE_HINT="${4:-}" OUT="$5"
  docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<PY
import json, time, urllib.request
sym, action, atr = "$SYM", "$ACTION", float("$ATR")
secret = "$SECRET"
price = float(json.loads(urllib.request.urlopen(
    f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}", timeout=8).read())["price"])
# 波动适配：ETH atr≈实盘1h量级；XAU atr≈金价波动
if action in ("LONG", "SHORT"):
    if action == "LONG":
        stop = round(price - 1.5 * atr, 2 if sym.startswith("ETH") else 3)
        tp1 = round(price + 1.35 * atr, 2 if sym.startswith("ETH") else 3)
        tp2 = round(price + 2.5 * atr, 2 if sym.startswith("ETH") else 3)
        tp3 = round(price + 4.0 * atr, 2 if sym.startswith("ETH") else 3)
    else:
        stop = round(price + 1.5 * atr, 2 if sym.startswith("ETH") else 3)
        tp1 = round(price - 1.35 * atr, 2 if sym.startswith("ETH") else 3)
        tp2 = round(price - 2.5 * atr, 2 if sym.startswith("ETH") else 3)
        tp3 = round(price - 4.0 * atr, 2 if sym.startswith("ETH") else 3)
    payload = {
        "symbol": sym + ".P", "action": action, "secret": secret,
        "price": round(price, 2 if sym.startswith("ETH") else 3),
        "tp1": tp1, "tp2": tp2, "tp3": tp3, "stop_loss": stop, "atr": atr,
        "regime": 3 if sym.startswith("ETH") else 1,
        "bar_index": int(time.time()), "seq": 1,
        "reason": f"whitepaper live {action} {sym}",
    }
else:
    payload = {
        "symbol": sym + ".P", "action": action, "secret": secret,
        "side": "$SIDE_HINT" or "LONG",
        "price": round(price, 2 if sym.startswith("ETH") else 3),
        "reason": f"whitepaper live {action} {sym}",
        "pnl_pct": -0.1, "bar_index": int(time.time()), "seq": 9,
    }
open("$OUT", "w").write(json.dumps(payload))
print(json.dumps(payload, ensure_ascii=False))
PY
}

verify_open() {
  local SYM="$1" EXPECT_SIDE="$2"
  docker compose exec -T -e PYTHONPATH=/app -w /app -e SYM="$SYM" -e EXPECT_SIDE="$EXPECT_SIDE" backend python - <<'PY'
import json, os
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient

sym = os.environ["SYM"]
expect = os.environ["EXPECT_SIDE"].upper()
db = SessionLocal()
u = db.query(User).filter(User.id == 6).one()
c = BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
pos = c.get_position(sym) or {}
amt = float(pos.get("positionAmt") or 0)
entry = float(pos.get("entryPrice") or 0)
mark = float(pos.get("markPrice") or entry)
notional = abs(amt) * mark
orders = c.client.futures_get_open_orders(symbol=sym) or []
try:
    algos = c.client._request_futures_api("get", "openAlgoOrders", True, {"symbol": sym}) or []
except Exception as e:
    algos = []; print("algo_err", e)
tp = [o for o in orders if str(o.get("type")) in ("LIMIT", "TAKE_PROFIT", "TAKE_PROFIT_MARKET") and str(o.get("reduceOnly")).lower() in ("true", "1")]
# classify stops
print("ORDERS:")
for o in orders:
    print(" ", o.get("type"), o.get("side"), o.get("origQty"), "@", o.get("stopPrice") or o.get("price"), "cid", o.get("clientOrderId"))
print("ALGOS:")
for a in algos:
    print(" ", a.get("orderType") or a.get("type"), a.get("quantity"), "@", a.get("triggerPrice") or a.get("stopPrice"), a.get("clientAlgoId") or a.get("algoId"))

key = f"binance_6_{sym.lower()}"
st = {}
for base in (Path("/app/data/supervisor"), Path("/home/panda/panda-quant-platform/backend/data/supervisor")):
    p = base / key / "state.json"
    if p.exists():
        st = json.loads(p.read_text()); break

hard = float(st.get("_frozen_hard_stop_px") or st.get("_tv_hard_sl_price") or 0)
radar = float(st.get("current_sl") or 0)
report = {
    "symbol": sym, "amt": amt, "entry": entry, "notional": round(notional, 2),
    "side_ok": (amt > 0 and expect == "LONG") or (amt < 0 and expect == "SHORT"),
    "orders": len(orders), "algos": len(algos), "tp_count": len(tp),
    "hard": hard, "radar": radar,
    "atr_scenario": st.get("atr_scenario"), "initial_atr": st.get("initial_atr"),
    "tp3_limit_active": st.get("tp3_limit_active"),
    "monitoring": st.get("monitoring"),
}
# hard vs radar distinct + both >0
report["dual_stop_ok"] = hard > 0 and radar > 0 and abs(hard - radar) > 1e-6
# TP1+TP2 exactly 2 preferred; never dozens at same price
from collections import Counter
px_counts = Counter(float(o.get("price") or 0) for o in tp)
report["max_same_tp_price"] = max(px_counts.values()) if px_counts else 0
report["tp_dup_ok"] = report["max_same_tp_price"] <= 1
report["stop_count"] = len(algos) + sum(1 for o in orders if "STOP" in str(o.get("type") or ""))
report["ok"] = (
    report["side_ok"] and notional >= 5 and report["dual_stop_ok"]
    and report["tp_count"] >= 2 and report["tp_dup_ok"]
    and report["stop_count"] >= 2 and report["max_same_tp_price"] <= 1
    and bool(st.get("monitoring")) and float(st.get("initial_atr") or 0) > 0
)
print(json.dumps(report, ensure_ascii=False, indent=2))
db.close()
raise SystemExit(0 if report["ok"] else 2)
PY
}

run_cycle() {
  local SYM="$1" ACTION="$2" ATR="$3" TAG="$4"
  echo "======== CYCLE $TAG $SYM $ACTION ========"
  build_payload "$SYM" "$ACTION" "$ATR" "" "/tmp/wp_${TAG}_open.json"
  # copy out of container
  docker compose cp backend:/tmp/wp_${TAG}_open.json /tmp/wp_${TAG}_open.json 2>/dev/null || true
  if [[ ! -f /tmp/wp_${TAG}_open.json ]]; then
    # rewrite on host
    docker compose exec -T backend cat /tmp/wp_${TAG}_open.json > /tmp/wp_${TAG}_open.json
  fi
  post_json /tmp/wp_${TAG}_open.json
  sleep 18
  verify_open "$SYM" "$ACTION"
  echo "=== hold 25s observe breath (no spam) ==="
  sleep 25
  docker compose logs --since 2m backend 2>/dev/null | grep -E "\[${SYM:0:3}\]|User 6|ATR_SCENARIO|硬止损|雷达|TP1|TP2|WebhookCoalesce|duplicate|FAIL|ERROR|Traceback" | tail -40 || true
  build_payload "$SYM" "CLOSE_QUICK_EXIT" "$ATR" "$ACTION" "/tmp/wp_${TAG}_close.json"
  docker compose exec -T backend cat /tmp/wp_${TAG}_close.json > /tmp/wp_${TAG}_close.json
  # wait >15s after open already; close is independent
  post_json /tmp/wp_${TAG}_close.json
  sleep 12
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
assert abs(amt)<1e-12 and len(orders)==0 and len(algos)==0, "post-close dirty"
print("POST_CLOSE_CLEAN_OK")
db.close()
PY
}

# --- 15s iron rule (ETH only) ---
echo "======== 15s IRON RULE ========"
build_payload ETHUSDT LONG 25 "" /tmp/wp_iron_open.json
docker compose exec -T backend cat /tmp/wp_iron_open.json > /tmp/wp_iron_open.json
post_json /tmp/wp_iron_open.json
sleep 4
build_payload ETHUSDT CLOSE_QUICK_EXIT 25 LONG /tmp/wp_iron_close_early.json
docker compose exec -T backend cat /tmp/wp_iron_close_early.json > /tmp/wp_iron_close_early.json
echo "=== CLOSE at +4s (must discard) ==="
post_json /tmp/wp_iron_close_early.json
sleep 8
docker compose logs --since 1m backend 2>/dev/null | grep -E "discarded_post_open|WebhookCoalesce" | tail -20 || true
verify_open ETHUSDT LONG
echo "=== CLOSE at +20s from open (must flatten) ==="
sleep 10
build_payload ETHUSDT CLOSE_QUICK_EXIT 25 LONG /tmp/wp_iron_close_late.json
docker compose exec -T backend cat /tmp/wp_iron_close_late.json > /tmp/wp_iron_close_late.json
post_json /tmp/wp_iron_close_late.json
sleep 12

# --- four smoke groups ---
run_cycle ETHUSDT LONG 25 eth_long
run_cycle ETHUSDT SHORT 25 eth_short
run_cycle XAUUSDT LONG 12 xau_long
run_cycle XAUUSDT SHORT 12 xau_short

echo "===FINAL CLEAN==="
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
  print(sym, "amt", amt, "orders", len(orders), "algos", len(algos))
  if abs(amt)>1e-12 or orders or algos: ok=False
print("FINAL_OK" if ok else "FINAL_DIRTY")
raise SystemExit(0 if ok else 3)
PY
echo "===WHITEPAPAR FINAL LIVE DONE==="
