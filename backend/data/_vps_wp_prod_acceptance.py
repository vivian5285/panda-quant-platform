#!/usr/bin/env python3
"""Whitepaper v3.0 production acceptance — rate-limit friendly.

Phases:
  A) In-process probes (radar arm 0.85/1.00 / reentry / hard 1.15 / rest pace)
     — zero exchange REST
  B) Live webhook cycles: ETH L→S, XAU L→S separately (~22U)
     After coalesce (~18s), sparse polls prove hard+TP hung in parallel at open
     (radar STOP only after arm path; hard+TP must exist on first readable snap)
  C) Restore E2E=0, flat book, print GO/NO-GO

Evidence: /tmp/wp_prod_accept/evidence_*
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import time
import urllib.request
from pathlib import Path

SECRET = os.environ.get("WEBHOOK_SECRET", "528586")
WH = "http://127.0.0.1:6010/webhook"
ROOT = Path("/home/panda/panda-quant-platform")
EVID = Path(f"/tmp/wp_prod_accept/evidence_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
EVID.mkdir(parents=True, exist_ok=True)
# Cool-downs between REST-heavy cycles (Binance -1003 / 429)
COOL_AFTER_CYCLE_SEC = int(os.environ.get("WP_COOL_SEC", "180"))
# Webhook coalesce buffers OPEN up to ~15s — first poll must be AFTER flush
COALESCE_WAIT_SEC = float(os.environ.get("WP_COALESCE_WAIT", "18"))
# Sparse polls after coalesce (absolute seconds from webhook HTTP return)
EARLY_POLLS = tuple(
    int(x) for x in os.environ.get("WP_EARLY_POLLS", "20,32").split(",") if x.strip()
)


def sh(cmd: str, check: bool = True) -> str:
    p = subprocess.run(cmd, shell=True, cwd=str(ROOT), capture_output=True, text=True)
    out = (p.stdout or "") + (p.stderr or "")
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd failed rc={p.returncode}: {cmd}\n{out[:2000]}")
    return out


def health() -> dict:
    with urllib.request.urlopen("http://127.0.0.1:6010/health", timeout=5) as r:
        return json.loads(r.read().decode())


def wait_health(n: int = 40) -> None:
    for _ in range(n):
        try:
            health()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("health timeout")


def public_price(sym: str) -> float:
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}"
    with urllib.request.urlopen(url, timeout=8) as r:
        return float(json.loads(r.read().decode())["price"])


def post_webhook(payload: dict, timeout: int = 120) -> str:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(WH, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def _docker_py(code: str) -> str:
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "-e", "PYTHONPATH=/app", "-w", "/app", "backend", "python", "-"],
        input=code,
        text=True,
        cwd=str(ROOT),
        capture_output=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        raise RuntimeError(out[-3000:])
    return p.stdout or ""


def set_e2e(val: float) -> None:
    env = ROOT / "backend" / ".env"
    text = env.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith("E2E_FORCE_NOTIONAL_USD="):
            lines[i] = f"E2E_FORCE_NOTIONAL_USD={val:g}"
            found = True
            break
    if not found:
        lines.append(f"E2E_FORCE_NOTIONAL_USD={val:g}")
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sh("docker compose up -d --force-recreate --no-deps backend")
    wait_health()
    time.sleep(10)


def preclean() -> str:
    return _docker_py(
        r"""
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
    time.sleep(2.0)
    rows=c.client.futures_position_information(symbol=sym) or []
    amt=float(next((r.get("positionAmt") for r in rows if abs(float(r.get("positionAmt") or 0))>1e-12), 0) or 0)
    if abs(amt)>1e-12:
        side="SELL" if amt>0 else "BUY"
        print(sym, "flatten", side, abs(amt))
        c.place_market_order(side, abs(amt), sym, reduce_only=True); time.sleep(2)
    try: c.cancel_all_open_orders(sym)
    except Exception as e: print(sym, "cancel", e)
    for meth in ("cancel_all_algo_orders","cancel_all_close_stops"):
        fn=getattr(c, meth, None)
        if callable(fn):
            try: fn(sym)
            except Exception as e: print(sym, meth, e)
    if hasattr(c,"_mop_up_leftover_orders"):
        try: c._mop_up_leftover_orders(sym, rounds=2)
        except Exception as e: print(sym, "mop", e)
    time.sleep(1.5)
    print(sym, "flat_ok")
db.close()
"""
    )


def snapshot(sym: str, action: str, tag: str) -> dict:
    code = f"""
import json
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
sym={sym!r}; action={action!r}; tag={tag!r}
db=SessionLocal(); u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
rows=c.client.futures_position_information(symbol=sym) or []
pos=next((r for r in rows if abs(float(r.get("positionAmt") or 0))>1e-12), None)
amt=float(pos.get("positionAmt") if pos else 0); entry=float(pos.get("entryPrice") if pos else 0)
mark=float((pos or {{}}).get("markPrice") or entry or 0)
orders=c.client.futures_get_open_orders(symbol=sym) or []
try: algos=c.client._request_futures_api("get","openAlgoOrders",True,data={{"symbol":sym}}) or []
except Exception as e: algos=[]; print("algo_err",e)
st={{}}
p=Path(f"/app/data/supervisor/binance_6_{{sym.lower()}}/state.json")
if p.exists(): st=json.loads(p.read_text())
hard=float(st.get("frozen_hard_stop_px") or st.get("tv_hard_sl_price") or 0)
radar=float(st.get("current_sl") or 0)
radar_on=bool(st.get("radar_activated") or False)
trend=st.get("trend_tier")
limits=[o for o in orders if str(o.get("type"))=="LIMIT"]
want_side="SELL" if action=="LONG" else "BUY"
ok_side_tp=[o for o in limits if str(o.get("side")).upper()==want_side]
wrong_side=[o for o in limits if str(o.get("side")).upper()!=want_side]
notional=round(abs(amt)*mark,2) if mark else 0
# ~22U: ETH often folds to 1–2 TP; require >=1 TP + hard STOP on book.
# Whitepaper v2: radar STOP is NOT hung until path TP1×0.85 — only hard before arm.
# After radar_activated: expect hard+radar (≥2 algo) when exchange query works.
algo_ok = len(algos) >= (2 if radar_on else 1)
defense_ok = (
  abs(amt)>1e-12 and 12<=notional<=55 and hard>0
  and len(ok_side_tp)>=1 and len(wrong_side)==0 and algo_ok
)
snap={{
  "tag":tag,"sym":sym,"action":action,"amt":amt,"entry":entry,"mark":mark,
  "notional":notional,"hard":hard,"radar":radar,"radar_activated":radar_on,
  "trend_tier":trend,"hard_ne_radar":abs(hard-radar)>0.5 if hard and radar else None,
  "atr_scenario":st.get("atr_scenario"),"n_limit":len(limits),
  "n_ok_side_tp":len(ok_side_tp),"n_wrong_side_tp":len(wrong_side),"n_algo":len(algos),
  "algo_prices":[float(a.get("triggerPrice") or a.get("stopPrice") or 0) for a in algos],
  "pass": bool(defense_ok),
}}
print(json.dumps(snap))
db.close()
"""
    raw = _docker_py(code).strip().splitlines()[-1]
    return json.loads(raw)


def flat_snap(sym: str) -> dict:
    code = f"""
import json
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
sym={sym!r}
db=SessionLocal(); u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
rows=c.client.futures_position_information(symbol=sym) or []
amt=float(next((r.get("positionAmt") for r in rows if abs(float(r.get("positionAmt") or 0))>1e-12), 0) or 0)
orders=c.client.futures_get_open_orders(symbol=sym) or []
try: algos=c.client._request_futures_api("get","openAlgoOrders",True,data={{"symbol":sym}}) or []
except Exception: algos=[]
st={{}}
p=Path(f"/app/data/supervisor/binance_6_{{sym.lower()}}/state.json")
if p.exists(): st=json.loads(p.read_text())
snap={{"sym":sym,"amt":amt,"n_orders":len(orders),"n_algo":len(algos),
      "watched_qty":st.get("watched_qty"),
      "pass_flat": abs(amt)<1e-12 and len(orders)==0 and len(algos)==0}}
print(json.dumps(snap))
db.close()
"""
    raw = _docker_py(code).strip().splitlines()[-1]
    return json.loads(raw)


def phase_a_probes() -> dict:
    """No exchange calls — whitepaper logic + radar activate path."""
    out = _docker_py(
        r"""
import json, time
from app.core.trend_tier_params import (
    MAX_REENTRY, RADAR_ARM_TP1_PCT, RADAR_ARM_TP1_PCT_REENTRY,
    HARD_STOP_BUFFER_FIXED, adx_to_tier, hard_buffer_for_tier,
    radar_arm_trigger_price, params_for_tier,
)
from app.core.breathing_stop import compute_temp_tv_stop, apply_breathing_tick
from app.core.smart_reentry import (
    close_allows_reentry, reentry_within_window, compute_optimal_reentry_price,
    tier_for_attempt, MAX_REENTRY as MR2, ARM_TP1_PCTS,
)
from app.core.rest_symbol_pace import MIN_GAP_SEC
from app.core.order_place_guard import PendingOrderRegistry
from app.core.adverse_radar_guard import OPEN_ORDERS_HARD_CAP
assert MAX_REENTRY == MR2 == 1
assert RADAR_ARM_TP1_PCT == 0.85 and RADAR_ARM_TP1_PCT_REENTRY == 1.00
assert ARM_TP1_PCTS == (0.85, 1.00)
assert HARD_STOP_BUFFER_FIXED == 1.15
assert abs(MIN_GAP_SEC - 0.100) < 1e-9
assert int(OPEN_ORDERS_HARD_CAP) == 5
reg = PendingOrderRegistry()
ok1,_ = reg.try_acquire("t-eth-re", kind="reentry", symbol="ETHUSDT")
ok2,_ = reg.try_acquire("t-eth-re", kind="reentry", symbol="ETHUSDT")
assert ok1 and not ok2
reg.release("t-eth-re")
assert adx_to_tier(15)==0 and adx_to_tier(25)==1 and adx_to_tier(35)==2
assert hard_buffer_for_tier(0)==hard_buffer_for_tier(1)==hard_buffer_for_tier(2)==1.15
assert abs(compute_temp_tv_stop(1900.80,"LONG",1874.0,tv_entry=1900.0)-1870.90)<1e-6
assert abs(radar_arm_trigger_price(side="LONG",fill_entry=1900.80,tp1=1925.65,tv_entry=1900.0,arm_pct=0.85)-1922.60)<0.01
# Reentry arm must NOT fire at 0.85 path
trig_re = radar_arm_trigger_price(side="LONG",fill_entry=1900.80,tp1=1925.65,tv_entry=1900.0,arm_pct=1.00)
mid = 1900.80 + abs(1925.65-1900.0)*0.85
assert mid + 1e-9 < trig_re
assert abs(trig_re - (1900.80 + 25.65)) < 1e-6
# ETH mid params
e=params_for_tier(1,"ETHUSDT"); x=params_for_tier(1,"XAUUSDT")
assert e.step_trigger_atr==0.5 and e.reentry_bars==2
assert x.step_trigger_atr==0.4 and x.reentry_bars==3
# Reentry after success: trail +1 AND arm=1.00
t=tier_for_attempt(1,"ETHUSDT",adx_tier=1)
assert t.radar_tier==2 and t.arm_tp1_pct==1.00
# Window
now=time.time()
ok,_=reentry_within_window(flat_ts=now-100, now_ts=now, symbol="ETHUSDT")
assert ok
ok,_=reentry_within_window(flat_ts=now-20000, now_ts=now, symbol="ETHUSDT")
assert not ok
ok,m=close_allows_reentry(side="LONG",entry=100,close_px=102,atr=10,symbol="ETHUSDT",close_track="radar")
assert ok
ok,m=close_allows_reentry(side="LONG",entry=100,close_px=102,atr=10,symbol="ETHUSDT",close_track="hard")
assert not ok and m["reason"]=="hard_stop_no_reentry"
ok,m=close_allows_reentry(side="LONG",entry=100,close_px=102,atr=10,symbol="ETHUSDT",close_track="radar",reentry_attempt=1)
assert not ok and m["reason"]=="max_reentry_once"
# Dual insurance
k5=[[0,"0","2010","1980","2000","0"]]
px,meta=compute_optimal_reentry_price(side="LONG",tv_px=2000,symbol="ETHUSDT",klines_5m=k5,last_entry=1990)
assert px>0 and meta["reason"]=="ok"
# Radar waits then activates at path 85% TP1
entry,atr=2000.0,20.0
tp1=entry+1.35*atr
initial=entry-1.5*atr
tick=apply_breathing_tick(side="LONG",price=entry+5,entry_price=entry,initial_atr=atr,
  initial_stop=initial,current_stop=initial,best_price=entry+5,breakeven_phase=False,
  symbol="ETHUSDT",arm_tp1_pct=0.85,tp1_price=tp1,radar_activated=False,
  step_trigger_atr=0.5,step_advance_atr=0.35,early_breakeven_atr=0.5,
  breath_tp1_tp2_atr=1.2,coef_min=2.0,coef_max=2.5)
assert tick["meta"]["event"]=="waiting_arm"
arm_px=radar_arm_trigger_price(side="LONG",entry=entry,tp1=tp1)
tick2=apply_breathing_tick(side="LONG",price=arm_px,entry_price=entry,initial_atr=atr,
  initial_stop=initial,current_stop=initial,best_price=arm_px,breakeven_phase=False,
  symbol="ETHUSDT",arm_tp1_pct=0.85,tp1_price=tp1,radar_activated=False,
  step_trigger_atr=0.5,step_advance_atr=0.35,early_breakeven_atr=0.5,
  breath_tp1_tp2_atr=1.2,coef_min=2.0,coef_max=2.5)
assert tick2["meta"].get("just_activated") or tick2["event"]=="radar_activate"
assert tick2["current_sl"] >= entry + 0.5*atr - 1e-6
print(json.dumps({"phase_a":"PASS","arm_px":arm_px,"activate_sl":tick2["current_sl"]}))
"""
    )
    line = out.strip().splitlines()[-1]
    return json.loads(line)


def build_open(sym: str, action: str, atr: float) -> dict:
    price = public_price(sym)
    if action == "LONG":
        stop = round(price - 1.5 * atr, 2)
        tp1 = round(price + 1.35 * atr, 2)
        tp2 = round(price + 2.5 * atr, 2)
        tp3 = round(price + 4.0 * atr, 2)
    else:
        stop = round(price + 1.5 * atr, 2)
        tp1 = round(price - 1.35 * atr, 2)
        tp2 = round(price - 2.5 * atr, 2)
        tp3 = round(price - 4.0 * atr, 2)
    return {
        "symbol": f"{sym}.P",
        "action": action,
        "secret": SECRET,
        "price": round(price, 2),
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "stop_loss": stop,
        "atr": atr,
        "adx": 25.0,  # mid tier
        "bar_index": int(time.time() * 1000) % 2000000000,
        "seq": random.randint(1, 99),
        "reason": f"wp_accept {sym} {action}",
    }


def run_cycle(sym: str, action: str, atr: float, tag: str) -> dict:
    d = EVID / tag
    d.mkdir(parents=True, exist_ok=True)
    payload = build_open(sym, action, atr)
    (d / "open_payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    t0 = time.time()
    try:
        open_resp = post_webhook(payload)
    except Exception as e:
        open_resp = f"ERROR {e}"
    (d / "open_http.txt").write_text(open_resp, encoding="utf-8")
    # Coalesce window: HTTP 200 "buffered" ≠ fill yet
    time.sleep(max(0.0, COALESCE_WAIT_SEC - (time.time() - t0)))

    early: list[dict] = []
    first_pass_sec = None
    book = None
    for target in EARLY_POLLS:
        wait = target - (time.time() - t0)
        if wait > 0:
            time.sleep(wait)
        try:
            snap = snapshot(sym, action, f"{tag}_t{target}")
        except Exception as e:
            snap = {"tag": f"{tag}_t{target}", "pass": False, "error": str(e)[:300]}
        snap["elapsed_sec"] = round(time.time() - t0, 1)
        early.append(snap)
        (d / f"book_t{target}.json").write_text(json.dumps(snap, indent=2), encoding="utf-8")
        print(json.dumps({"early": snap["tag"], "pass": snap.get("pass"), "n_tp": snap.get("n_ok_side_tp"),
                          "n_algo": snap.get("n_algo"), "hard": snap.get("hard"), "elapsed": snap["elapsed_sec"]}), flush=True)
        if snap.get("pass") and first_pass_sec is None:
            first_pass_sec = snap["elapsed_sec"]
            book = snap
            break
        book = snap
        if "1003" in str(snap.get("error") or "") or "429" in str(snap.get("error") or ""):
            break

    (d / "early_polls.json").write_text(json.dumps(early, indent=2), encoding="utf-8")
    if book is None:
        book = {"pass": False, "error": "no_snapshot"}

    # Ensure >15s since open before CLOSE (coalesce discard window)
    since = time.time() - t0
    if since < 16:
        time.sleep(16 - since)
    close_payload = {
        "symbol": f"{sym}.P",
        "action": "CLOSE_QUICK_EXIT",
        "secret": SECRET,
        "price": round(public_price(sym), 2),
        "bar_index": int(time.time() * 1000) % 2000000000,
        "seq": random.randint(1, 99),
        "reason": f"wp_accept close {tag}",
    }
    (d / "close_payload.json").write_text(json.dumps(close_payload, indent=2), encoding="utf-8")
    try:
        close_resp = post_webhook(close_payload, timeout=90)
    except Exception as e:
        close_resp = f"ERROR {e}"
    (d / "close_http.txt").write_text(close_resp, encoding="utf-8")
    time.sleep(18)
    # Extra mop if CLOSE left dust
    try:
        flat = flat_snap(sym)
        if not flat.get("pass_flat"):
            _docker_py(
                f"""
import time
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
sym={sym!r}
db=SessionLocal(); u=db.query(User).filter(User.id==6).one()
c=BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
rows=c.client.futures_position_information(symbol=sym) or []
amt=float(next((r.get("positionAmt") for r in rows if abs(float(r.get("positionAmt") or 0))>1e-12), 0) or 0)
if abs(amt)>1e-12:
    side="SELL" if amt>0 else "BUY"
    c.place_market_order(side, abs(amt), sym, reduce_only=True); time.sleep(2)
try: c.cancel_all_open_orders(sym)
except Exception: pass
for meth in ("cancel_all_algo_orders","cancel_all_close_stops"):
    fn=getattr(c,meth,None)
    if callable(fn):
        try: fn(sym)
        except Exception: pass
print("mop_ok")
db.close()
"""
            )
            time.sleep(3)
            flat = flat_snap(sym)
    except Exception as e:
        flat = {"pass_flat": False, "error": str(e)[:300]}
    (d / "book_flat.json").write_text(json.dumps(flat, indent=2), encoding="utf-8")
    return {
        "tag": tag,
        "open": book,
        "flat": flat,
        "first_defense_pass_sec": first_pass_sec,
        "early_polls": early,
        "open_http": open_resp[:400],
        "close_http": close_resp[:400],
        "parallel_defense": bool(first_pass_sec is not None and first_pass_sec <= 40),
        "note": "v2: pre-arm only hard STOP required; radar STOP after TP1 path x0.85",
    }


def main() -> None:
    head = sh("git rev-parse --short HEAD").strip()
    (EVID / "head.txt").write_text(head + "\n", encoding="utf-8")
    (EVID / "health_pre.json").write_text(json.dumps(health()), encoding="utf-8")

    print("=== PHASE A in-process probes ===")
    phase_a = phase_a_probes()
    (EVID / "phase_a.json").write_text(json.dumps(phase_a, indent=2), encoding="utf-8")
    print(json.dumps(phase_a))

    print("=== Enable E2E 22U + preclean ===")
    set_e2e(22)
    (EVID / "preclean.txt").write_text(preclean(), encoding="utf-8")

    # WP_ONLY=eth_long,eth_short,xau_long,xau_short 可子集
    # WP_FULL_MATRIX=1 → 四向全跑
    all_cycles = {
        "eth_long": ("ETHUSDT", "LONG", 12.0, "eth_long"),
        "eth_short": ("ETHUSDT", "SHORT", 12.0, "eth_short"),
        "xau_long": ("XAUUSDT", "LONG", 8.0, "xau_long"),
        "xau_short": ("XAUUSDT", "SHORT", 8.0, "xau_short"),
    }
    only = os.environ.get("WP_ONLY", "").strip()
    if only:
        keys = [k.strip() for k in only.split(",") if k.strip()]
        cycles = [all_cycles[k] for k in keys if k in all_cycles]
    elif os.environ.get("WP_FULL_MATRIX", "0") == "1":
        cycles = list(all_cycles.values())
    else:
        cycles = [all_cycles["eth_long"], all_cycles["xau_short"]]
    if not cycles:
        raise SystemExit("no cycles selected")

    results = []
    for i, (sym, action, atr, tag) in enumerate(cycles):
        print(f"=== CYCLE {tag} ===")
        try:
            r = run_cycle(sym, action, atr, tag)
        except Exception as e:
            r = {"tag": tag, "open": {"pass": False}, "flat": {"pass_flat": False}, "error": str(e)[:500]}
        results.append(r)
        (EVID / f"{tag}_result.json").write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")
        if i < len(cycles) - 1:
            print(f"rate-limit cool-down {COOL_AFTER_CYCLE_SEC}s...")
            time.sleep(COOL_AFTER_CYCLE_SEC)

    print("=== Restore E2E=0 + final flat ===")
    set_e2e(0)
    (EVID / "final_clean.txt").write_text(preclean(), encoding="utf-8")
    e2e = _docker_py("from app.config import get_settings; print(get_settings().E2E_FORCE_NOTIONAL_USD)").strip()
    eth_flat = flat_snap("ETHUSDT")
    xau_flat = flat_snap("XAUUSDT")

    all_open = all(r.get("open", {}).get("pass") for r in results)
    all_flat = all(r.get("flat", {}).get("pass_flat") for r in results)
    all_parallel = all(r.get("parallel_defense") for r in results if "parallel_defense" in r)
    ready = (
        all_open and all_flat and all_parallel
        and phase_a.get("phase_a") == "PASS"
        and float(e2e or 1) == 0
        and eth_flat.get("pass_flat") and xau_flat.get("pass_flat")
        and head == sh("git rev-parse --short HEAD").strip()
    )
    summary = {
        "head": head,
        "evid": str(EVID),
        "phase_a": phase_a,
        "results": [
            {
                "tag": r.get("tag"),
                "open_pass": r.get("open", {}).get("pass"),
                "flat_pass": r.get("flat", {}).get("pass_flat"),
                "first_defense_pass_sec": r.get("first_defense_pass_sec"),
                "parallel_defense": r.get("parallel_defense"),
                "n_tp": r.get("open", {}).get("n_ok_side_tp"),
                "n_algo": r.get("open", {}).get("n_algo"),
                "notional": r.get("open", {}).get("notional"),
                "error": r.get("error"),
            }
            for r in results
        ],
        "e2e_restored": e2e,
        "final_flat": {"ETH": eth_flat, "XAU": xau_flat},
        "all_open_pass": all_open,
        "all_flat_pass": all_flat,
        "all_parallel_defense": all_parallel,
        "GO_WAIT_REAL_TV": ready,
    }
    (EVID / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("GO_WAIT_REAL_TV" if ready else "NO_GO")
    print("EVID", EVID)


if __name__ == "__main__":
    main()
