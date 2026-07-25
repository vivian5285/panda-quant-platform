#!/bin/bash
# Full-function production checklist probe (read-only + assertions)
set -eu
cd /home/panda/panda-quant-platform
echo "===UTC $(date -u +%Y-%m-%dT%H:%M:%SZ)==="
echo "VPS_HEAD=$(git rev-parse HEAD)"
echo "VPS_SHORT=$(git rev-parse --short HEAD)"
echo "VPS_ONELINE=$(git log -1 --oneline)"
curl -sf -m 5 http://127.0.0.1:6010/health; echo
curl -sf -m 5 http://127.0.0.1:8000/api/health 2>/dev/null || curl -sf -m 5 http://127.0.0.1:8000/health || true
echo

docker compose exec -T -e PYTHONPATH=/app -w /app backend python - <<'PY'
from app.core.tv_entry_sizing import compute_tv_entry_qty
from app.core.breathing_profile import ETH_PROFILE, XAU_PROFILE, cold_start_multiplier, RATIO_FLOOR, RATIO_CEILING
from app.core.breathing_stop import resolve_breathing_coef, get_breathing_coefficient
from app.core.tp_regime_targets import FIXED_TP_QTY_PERCENT, PLACEABLE_TP_LEVELS, resolve_tp_ratios_from_payload
from app.core.symbol_registry import supervisor_state_key
from app.core.initial_atr_lock import InitialAtrDescriptor, blocked_initial_atr_writes
from app.services.platform_runtime import is_global_trading_paused
import inspect

# 1) qty-free sizing
q, m = compute_tv_entry_qty(
    live_balance=1000, initial_principal=1000, price=2000,
    tv_sl=1970, tv_stop_loss=1970, exchange_leverage=5,
    tv_qty=None, symbol="ETHUSDT",
)
assert q > 0 and m.get("error") is None and m.get("binding") == "margin20_lev5", m
assert abs(q * 2000 - 1000) < 2.0
assert m.get("tv_qty_ignored") is True
assert m.get("adjust_coef") is None
print("SIZING_NO_QTY_OK", q, m.get("binding"))

# 2) TP ratios
assert tuple(FIXED_TP_QTY_PERCENT) == (10, 20, 70)
assert PLACEABLE_TP_LEVELS == frozenset({1, 2, 3})
assert resolve_tp_ratios_from_payload({"qty1": 9, "qty2": 9}) == [0.1, 0.2, 0.7]
print("TP_10_20_70_OK")

# 3) breath params
assert ETH_PROFILE.coef_min == 1.2 and ETH_PROFILE.coef_max == 2.5
assert XAU_PROFILE.coef_min == 0.5 and XAU_PROFILE.coef_max == 1.2
assert abs(cold_start_multiplier(ETH_PROFILE) - 1.525) < 1e-9
assert abs(cold_start_multiplier(XAU_PROFILE) - 0.675) < 1e-9
assert RATIO_FLOOR == 0.6 and RATIO_CEILING == 2.2
assert get_breathing_coefficient(1.0, "XAUUSDT") < get_breathing_coefficient(1.0, "ETHUSDT")
print("BREATH_PARAMS_OK")

# 4) initial_atr lock
class H:
    initial_atr = InitialAtrDescriptor()
h = H(); h.initial_atr = 14.0; h.initial_atr = 99.0
assert h.initial_atr == 14.0 and blocked_initial_atr_writes(h) == 1
print("INITIAL_ATR_LOCK_OK")

# 5) isolation keys
assert supervisor_state_key("binance", 6, "ETHUSDT") == "binance_6_ethusdt"
assert supervisor_state_key("binance", 6, "XAUUSDT") == "binance_6_xauusdt"
print("ISOLATION_KEYS_OK")

# 6) book fail-closed markers
from app.core import binance_client as bc
src = inspect.getsource(bc.BinanceClient)
assert "_mop_up_leftover_orders" in src or "mop_up" in src.lower()
assert "BookFetchError" in src or "book_unknown" in src.lower() or "leftover" in src.lower()
print("BOOK_GUARD_MARKERS_OK")

# 7) FIXED leverage theme
from app.core.tv_entry_sizing import FIXED_LEVERAGE, MAX_LEVERAGE
assert int(FIXED_LEVERAGE) == 5 and int(MAX_LEVERAGE) == 5
print("LEVERAGE5_OK")

print("global_paused", is_global_trading_paused())
print("CHECKLIST_PROBE_OK")
PY

echo "===SUPERVISOR STATE==="
python3 - <<'PY'
import json
from pathlib import Path
for p in sorted(Path("backend/data/supervisor").glob("binance_6_*/state.json")):
    d=json.loads(p.read_text())
    print(p.parent.name, {
        "paused": d.get("trading_paused"),
        "qty": d.get("watched_qty"),
        "side": d.get("current_side"),
        "mon": d.get("monitoring"),
        "schema": d.get("schema_version"),
    })
PY

echo "===RECENT ALERTS/ERR (10m)==="
docker compose logs backend --since 10m 2>/dev/null | grep -Ei 'ERROR|CRITICAL|IP banned|-1003|DUP|FLAT_ORDERS|OPEN_BOOK_DIRTY|Traceback' | tail -n 30 || echo NONE
echo "===PROBE DONE==="
