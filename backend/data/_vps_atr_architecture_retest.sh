#!/bin/bash
# ATR architecture补测: (1) abnormal atr reject ×3×2 symbols (2) 30m breath hold ETH+XAU
set -eu
cd /home/panda/panda-quant-platform
WH_URL="${WEBHOOK_URL:-https://twinstar.pro/gemini/webhook}"
SECRET=528586
OBS=/home/panda/panda-quant-platform/backend/data/_atr_breath_observe.jsonl
REPORT=/home/panda/panda-quant-platform/backend/data/_atr_architecture_retest_report.json
LOG_EVIDENCE=/home/panda/panda-quant-platform/backend/data/_atr_reject_evidence.txt

echo "===UTC $(date -u +%Y-%m-%dT%H:%M:%SZ) HEAD=$(git log -1 --oneline)==="
curl -sf -m 5 http://127.0.0.1:6010/health; echo

echo "===PREFLIGHT flat user6==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
import json, time
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient

db = SessionLocal()
u = db.query(User).filter(User.id == 6).one()
c = BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
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
                  "trading_paused": False})
        p.write_text(json.dumps(s, ensure_ascii=False))
db.close()
print("PREFLIGHT_OK")
PY

: > "$LOG_EVIDENCE"
echo "===PART1 abnormal ATR reject (ETH + XAU)===" | tee -a "$LOG_EVIDENCE"

post_abnormal() {
  local SYM="$1" CASE="$2" ATR_JSON="$3"
  local TS
  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  python3 - <<PY
import json, time, urllib.request
sym="$SYM"; case="$CASE"; secret="$SECRET"
atr_raw = '''$ATR_JSON'''
price=float(json.loads(urllib.request.urlopen(
  f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}", timeout=10).read())["price"])
atr = 14.5 if "ETH" in sym else 8.0
payload={
  "symbol": f"{sym}.P", "action": "LONG", "secret": secret,
  "price": round(price, 2), "qty": 0.02,
  "tp1": round(price + 1.35*atr, 2),
  "tp2": round(price + 2.5*atr, 2),
  "tp3": round(price + 4.0*atr, 2),
  "stop_loss": round(price - 1.5*atr, 2),
  "regime": 3, "bar_index": int(time.time()), "seq": 1,
  "reason": f"ATR reject case {case}",
}
if atr_raw.strip() != "MISSING":
    payload["atr"] = json.loads(atr_raw)
path=f"/tmp/atr_rej_{sym.lower()}_{case}.json"
open(path,"w").write(json.dumps(payload))
print("CASE", case, "SYM", sym, "payload_atr", payload.get("atr", "<MISSING>"))
PY
  local RESP HTTP
  RESP=$(curl -sS -m 30 -w "\nHTTP=%{http_code}" -H 'Content-Type: application/json' \
    -d @"/tmp/atr_rej_${SYM,,}_${CASE}.json" "$WH_URL" || true)
  echo "[$TS] $SYM case=$CASE" | tee -a "$LOG_EVIDENCE"
  echo "$RESP" | tee -a "$LOG_EVIDENCE"
  echo "---" | tee -a "$LOG_EVIDENCE"
  sleep 2
}

for SYM in ETHUSDT XAUUSDT; do
  post_abnormal "$SYM" missing MISSING
  post_abnormal "$SYM" zero 0
  post_abnormal "$SYM" negative -3.5
done

echo "===PART1 backend log evidence (ATR_INVALID / atr must)===" | tee -a "$LOG_EVIDENCE"
docker compose logs --since 10m backend 2>&1 | grep -E "ATR_INVALID|atr must|Missing required field.*atr|开仓拒绝·ATR|ATR无效" | tail -80 | tee -a "$LOG_EVIDENCE"

echo "===VERIFY still flat after rejects==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
db = SessionLocal()
u = db.query(User).filter(User.id == 6).one()
c = BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
for sym in ("ETHUSDT", "XAUUSDT"):
    pos = c.get_position(sym) or {}
    amt = float(pos.get("positionAmt") or 0)
    print(sym, "amt", amt, "OK_FLAT" if abs(amt)<1e-12 else "NOT_FLAT")
db.close()
PY

echo "===PART2 open ETH+XAU with valid atr, observe ~32 min==="
post_open() {
  local SYM="$1" ATR="$2"
  python3 - <<PY
import json, time, urllib.request
sym="$SYM"; atr=float("$ATR"); secret="$SECRET"
price=float(json.loads(urllib.request.urlopen(
  f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}", timeout=10).read())["price"])
payload={
  "symbol": f"{sym}.P", "action": "LONG", "secret": secret,
  "price": round(price, 2), "qty": 0.02,
  "tp1": round(price + 1.35*atr, 2),
  "tp2": round(price + 2.5*atr, 2),
  "tp3": round(price + 4.0*atr, 2),
  "stop_loss": round(price - 1.5*atr, 2),
  "atr": atr, "regime": 3,
  "bar_index": int(time.time()), "seq": 1,
  "reason": "ATR breath observe 30m",
}
path=f"/tmp/atr_obs_{sym.lower()}_open.json"
open(path,"w").write(json.dumps(payload))
print("OPEN", sym, "atr", atr, "price", price)
PY
  curl -sS -m 60 -w "\nHTTP=%{http_code}\n" -H 'Content-Type: application/json' \
    -d @"/tmp/atr_obs_${SYM,,}_open.json" "$WH_URL"
  echo
}

post_open ETHUSDT 14.5
sleep 20
post_open XAUUSDT 8.0
sleep 15

OBS=/home/panda/panda-quant-platform/backend/data/_atr_breath_observe.jsonl
: > "$OBS"
echo "===Observe 7 samples every 5 min (≈30m)==="
for i in 1 2 3 4 5 6 7; do
  echo "sample_$i $(date -u +%H:%M:%SZ)"
  docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<PY
import json, time
from pathlib import Path
ts = time.time()
row = {"sample": $i, "ts": ts, "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))}
for name, can in (("binance_6_ethusdt","ETHUSDT"), ("binance_6_xauusdt","XAUUSDT")):
    p = Path(f"/app/data/supervisor/{name}/state.json")
    s = json.loads(p.read_text()) if p.exists() else {}
    row[can] = {
        "initial_atr": s.get("initial_atr"),
        "atr_1h": s.get("atr_1h"),
        "current_atr": s.get("current_atr"),
        "tv_atr_ref": s.get("tv_atr_ref"),
        "breathing_coefficient": s.get("breathing_coefficient"),
        "breath_ratio_history": s.get("breath_ratio_history"),
        "watched_qty": s.get("watched_qty"),
        "current_side": s.get("current_side"),
        "monitoring": s.get("monitoring"),
    }
line = json.dumps(row, ensure_ascii=False)
print(line)
with open("/app/data/_atr_breath_observe.jsonl", "a", encoding="utf-8") as f:
    f.write(line + "\n")
PY
  if [ "$i" -lt 7 ]; then
    sleep 300
  fi
done

echo "===FLATTEN both==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
import time
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
db = SessionLocal()
u = db.query(User).filter(User.id == 6).one()
c = BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
for sym in ("ETHUSDT", "XAUUSDT"):
    try:
        c.cancel_all_open_orders(sym)
    except Exception as e:
        print(sym, "cancel", e)
    pos = c.get_position(sym) or {}
    amt = float(pos.get("positionAmt") or 0)
    if abs(amt) > 1e-12:
        side = "SELL" if amt > 0 else "BUY"
        print(sym, "flat", c.place_market_order(side, abs(amt), sym, reduce_only=True))
    else:
        print(sym, "already_flat")
db.close()
print("FLATTEN_DONE")
PY

python3 - <<PY
import json, subprocess
from pathlib import Path
obs=[]
p=Path("/home/panda/panda-quant-platform/backend/data/_atr_breath_observe.jsonl")
if p.exists():
    for line in p.read_text().splitlines():
        line=line.strip()
        if not line: continue
        try: obs.append(json.loads(line))
        except Exception: pass
head = subprocess.check_output(["git","-C","/home/panda/panda-quant-platform","log","-1","--oneline"], text=True).strip()
report={
  "head": head,
  "reject_evidence_file": "/home/panda/panda-quant-platform/backend/data/_atr_reject_evidence.txt",
  "observe_samples": obs,
}
for can in ("ETHUSDT","XAUUSDT"):
    inits=[(r.get(can) or {}).get("initial_atr") for r in obs]
    atrs=[(r.get(can) or {}).get("atr_1h") for r in obs]
    coefs=[(r.get(can) or {}).get("breathing_coefficient") for r in obs]
    report[f"{can}_initial_atr_series"]=inits
    report[f"{can}_atr_1h_series"]=atrs
    report[f"{can}_coef_series"]=coefs
    report[f"{can}_initial_frozen"]=len(set([x for x in inits if x is not None]))<=1
Path("/home/panda/panda-quant-platform/backend/data/_atr_architecture_retest_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2)
)
print("REPORT written")
print(json.dumps({k:report[k] for k in report if k!="observe_samples"}, ensure_ascii=False, indent=2))
PY

echo "===DONE==="
