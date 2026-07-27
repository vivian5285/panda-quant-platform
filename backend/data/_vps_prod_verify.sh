set -u
cd /home/panda/panda-quant-platform
echo "===HEAD==="
git rev-parse HEAD
git rev-parse --short HEAD
git log -1 --oneline
curl -sf http://127.0.0.1:6010/health; echo
curl -sf http://127.0.0.1:8000/health || echo "8000_health_fail"
echo
echo "===CODE VERIFY==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
from app.config import get_settings
from app.core.breathing_stop import TEMP_TV_STOP_BUFFER, compute_temp_tv_stop
from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.open_atr_scenario import ATR_SCENARIO_VPS, ATR_SCENARIO_TV
from app.services.webhook_symbol_coalesce import COALESCE_WINDOW_MAX_SEC, POST_OPEN_CLOSE_DISCARD_SEC
import inspect
import app.core.open_atr_scenario as oas
import app.core.adverse_radar_guard as arg
s = get_settings()
print("COALESCE_SEC", s.WEBHOOK_COALESCE_SEC)
print("E2E_FORCE", getattr(s, "E2E_FORCE_NOTIONAL_USD", None))
print("TEMP_TV_STOP_BUFFER", TEMP_TV_STOP_BUFFER)
print("LONG_example", compute_temp_tv_stop(1900, "LONG", 1880))  # expect 1876
print("SHORT_example", compute_temp_tv_stop(1900, "SHORT", 1920))  # expect 1924
print("dual_track", AdverseRadarMixin._uses_dual_stop_track(AdverseRadarMixin))
print("WINDOW_MAX", COALESCE_WINDOW_MAX_SEC, "DISCARD", POST_OPEN_CLOSE_DISCARD_SEC)
print("SCENARIOS", ATR_SCENARIO_VPS, ATR_SCENARIO_TV)
src = inspect.getsource(oas.apply_vps_atr_upgrade)
assert "_frozen_hard_stop_px" in src
hs = inspect.getsource(arg.AdverseRadarMixin._sync_hard_stop_only)
assert "never cancel/reprice" in hs or "immutable" in hs
assert abs(compute_temp_tv_stop(1900, "LONG", 1880) - 1876.0) < 1e-6
assert abs(compute_temp_tv_stop(1900, "SHORT", 1920) - 1924.0) < 1e-6
assert float(s.WEBHOOK_COALESCE_SEC) == 10.0
print("SOURCE_MARKERS_OK")
PY
echo "===FLAT CLEAN==="
docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
import json, time
from pathlib import Path
from app.database import SessionLocal
from app.models import User
from app.utils.crypto import decrypt_text
from app.core.binance_client import BinanceClient
from app.services.trading_control import is_globally_paused, is_user_paused, set_user_paused

db = SessionLocal()
print("global_paused", is_globally_paused())
if is_user_paused(db, 6):
    set_user_paused(db, 6, False, reason="prod_deploy_unpause")
print("user6_paused", is_user_paused(db, 6))
u = db.query(User).filter(User.id == 6).one()
c = BinanceClient(decrypt_text(u.api_key_enc), decrypt_text(u.api_secret_enc), user_id=6)
summary = c.get_futures_account_summary() or {}
print("equity", summary.get("total_margin_balance") or summary.get("totalWalletBalance"))
for sym in ("ETHUSDT", "XAUUSDT"):
    try:
        c.cancel_all_open_orders(sym)
    except Exception as e:
        print(sym, "cancel_orders", type(e).__name__)
    for meth in ("cancel_all_algo_orders", "cancel_all_close_stops"):
        fn = getattr(c, meth, None)
        if callable(fn):
            try:
                print(sym, meth, fn(sym))
            except Exception as e:
                print(sym, meth, type(e).__name__)
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
        print(sym, "algo_cleanup", type(e).__name__)
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
    amt2 = float((c.get_position(sym) or {}).get("positionAmt") or 0)
    print(sym, "flat", abs(amt2) < 1e-12, "orders", len(orders), "algos", len(algos))
    assert abs(amt2) < 1e-12 and len(orders) == 0 and len(algos) == 0, sym
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
        print("state_reset", str(p))
db.close()
print("FLAT_CLEAN_OK")
PY
echo "===BAN PHRASE SAMPLE==="
docker compose exec -T backend sh -c 'grep -RIn --include="*.py" -E "保护性全平|加仓成交|雷达激活" /app/app 2>/dev/null | head -10 || echo NONE'
echo "===LOGS recent errors==="
docker compose logs --since 3m backend 2>/dev/null | grep -E "Traceback|ERROR|trading_paused|FORCE_ALIGN" | tail -30 || true
echo "===VERIFY DONE==="
